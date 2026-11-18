"""Desktop smoke check for heat-map cell gaps, vector geometry, and readable axis labels.

``tramastat.py --smoke`` calls :func:`check_heat_map_layout` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=heatmap-layout python tramastat.py --smoke DIR``.

Synthetic data only. Outputs, logs, exports, and screenshots go to ``DIR/heatmap-layout``.
"""
import json
import shutil
import time
import tracemalloc
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch
from xml.etree import ElementTree as ET

from matplotlib.collections import PolyCollection, QuadMesh
import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .heatmap import (
    CATEGORY_COLORS,
    HEAT_MAP,
    ORIENTATION,
    REVERSE_LEGEND,
)
from .heatmap_layout import (
    COLUMN_GAP_MODE,
    COLUMN_GAP_SIZE,
    COLUMN_GAPS_AFTER,
    COLUMN_LABEL_EVERY,
    COLUMN_LABEL_FONT_SIZE,
    COLUMN_LABEL_FREQUENCY,
    COLUMN_LABEL_ROTATION,
    COLUMN_LABEL_SIDE,
    ROW_GAP_MODE,
    ROW_GAP_SIZE,
    ROW_GAPS_AFTER,
    ROW_LABEL_EVERY,
    ROW_LABEL_FONT_SIZE,
    ROW_LABEL_FREQUENCY,
    ROW_LABEL_SIDE,
    SHOW_COLUMN_LABELS,
    SHOW_ROW_LABELS,
    layout_geometry,
)

FIXTURES_072 = Path(__file__).resolve().parent.parent / "tests" / "data" / "heatmap_072"
LEGACY = json.loads((FIXTURES_072 / "legacy-072.json").read_text(encoding="utf-8"))


def check_heat_map_layout(root, app, directory, tools):
    """Exercise legacy identity, gap geometry, axis labels, EN/IT dialogs, recovery, exports, and 80x120 stress."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "heatmap-layout"
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
        assert "Traceback" not in message and "OverflowError" not in message, message
        page = dialog.field_rows[field][1].master
        while page.master is not dialog.fields:
            page = page.master
        assert dialog.fields.select() == str(page), field
        assert dialog.focus_get() is focus_target(dialog.field_rows[field][1]), dialog.focus_get()
        if shot_name:
            shot(dialog, shot_name)
        return message

    def find_run(title, number=0):
        return [i for i, run in enumerate(app.runs) if run.title == title][number]

    def edit(index, action, initial_field=ROW_GAP_MODE):
        app.show("graph", index)
        root.update()
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.edit_analysis(initial_field=initial_field)
        wait()

    def poly_collection(index):
        figure = app.runs[index].result.figure
        found = next(c for ax in figure.axes for c in ax.collections if isinstance(c, PolyCollection))
        found.update_scalarmappable()
        return found

    def quad_mesh(index):
        figure = app.runs[index].result.figure
        found = next(c for ax in figure.axes for c in ax.collections if isinstance(c, QuadMesh))
        found.update_scalarmappable()
        return found

    try:
        # 1. Legacy project without layout keys: identical QuadMesh RGBA, no Heat map layout table, no new keys.
        legacy_path = out / "heatmap-layout-legacy.alab"
        shutil.copy(FIXTURES_072 / "legacy-072.alab", legacy_path)
        app.import_file(legacy_path)
        legacy_idx = find_run("Numeric", 0)
        app.open_sheet(("graph", legacy_idx))
        wait()
        np.testing.assert_allclose(quad_mesh(legacy_idx).get_facecolors(), LEGACY["matrix"]["rgba"], rtol=1e-12, atol=1e-12)
        assert list(app.runs[legacy_idx].result.tables) == ["Heat map data"]
        for key in (ROW_GAP_MODE, COLUMN_GAP_MODE, SHOW_ROW_LABELS, SHOW_COLUMN_LABELS):
            assert key not in app.runs[legacy_idx].options

        # 2. Synthetic Matrix, Long numeric, Long categories, and 80x120 stress datasets.
        matrix_df = pd.DataFrame({
            "Row": ["r1", "dup", "dup", "$ATP$"],
            "A": [1.234, 0.0, 0.00001234, 7.0],
            "B": [-0.0001, 1000.0, 2.5, 8.0],
            "C": [np.nan, -12.3456, 3.0, 9.0],
            "D": [4.0, 5.0, 6.0, 10.0],
        })
        long_num_df = pd.DataFrame({
            "Row": ["r1", "r1", "r1", "r2", "r2", "r3", "r3"],
            "Column": ["A", "A", "B", "A", "B", "A", "B"],
            "Value": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0, np.nan],
        })
        cat_df = pd.DataFrame({
            "Row": ["r1", "r1", "r2", "r2", "r3", "r3"],
            "Column": ["A", "B", "A", "B", "A", "B"],
            "Value": ["$ATP$", "low", "high", None, "low", "high"],
        })
        rng = np.random.default_rng(11)
        stress_cols = [f"C{j:03d}" for j in range(120)]
        stress_dict = {"Row": [f"R{i:02d}" for i in range(80)]}
        for j, name in enumerate(stress_cols):
            stress_dict[name] = rng.normal(loc=j * 0.05, size=80)
        stress_df = pd.DataFrame(stress_dict)

        work_path = out / "heatmap-layout-work.alab"
        matrix_opts = {
            "Input format": "Matrix", "Variables": ["A", "B", "C", "D"], "Row labels": "Row",
            "Show cell values": True, "Mark missing cells": True, "Show color legend": False,
        }
        long_opts = {
            "Input format": "Long numeric", "X categories": "Column", "Y categories": "Row", "Values": "Value",
            "Cell value": "Mean", "Show cell values": True, "Mark missing cells": True,
            ORIENTATION: "Horizontal", REVERSE_LEGEND: True,
        }
        cat_opts = {
            "Input format": "Long categories", "X categories": "Column", "Y categories": "Row", "Values": "Value",
            "Show cell values": True, "Mark missing cells": True,
            CATEGORY_COLORS: {"$ATP$": "#cc3311", "high": "#114477"},
        }
        stress_opts = {
            "Input format": "Matrix", "Variables": stress_cols, "Row labels": "Row",
            ROW_GAP_MODE: "Every boundary", ROW_GAP_SIZE: 0.15,
            COLUMN_GAP_MODE: "Every boundary", COLUMN_GAP_SIZE: 0.15,
        }
        save_project(work_path, {
            "Matrix": Dataset(matrix_df, analyses=[(HEAT_MAP, matrix_opts)]),
            "LongNum": Dataset(long_num_df, analyses=[(HEAT_MAP, long_opts)]),
            "Categories": Dataset(cat_df, analyses=[(HEAT_MAP, cat_opts)]),
            "Stress80x120": Dataset(stress_df, analyses=[(HEAT_MAP, stress_opts)]),
        })
        app.import_file(work_path)
        mat_idx = find_run("Matrix", 0)
        long_idx = find_run("LongNum", 0)
        cat_idx = find_run("Categories", 0)
        stress_idx = find_run("Stress80x120", 0)

        app.open_sheet(("graph", mat_idx))
        wait()
        legacy_matrix_data = app.runs[mat_idx].result.tables["Heat map data"].copy()
        legacy_matrix_rgba = quad_mesh(mat_idx).get_facecolors().copy()

        # 3. 1024x768 main window: Every -> size 0 -> None with bad hidden values -> Selected errors -> decimal comma fix.
        root.geometry("1024x768+0+0")
        root.update()
        # Resizing the main window does not change the screen used for dialog placement.
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()

        def validate_and_configure_en(dialog):
            controls = dialog.controls
            controls[ROW_GAP_MODE][1].set("Every boundary")
            controls[ROW_GAP_SIZE][1].set("0")
            dialog.update()
            assert placed(dialog, ROW_GAP_SIZE) and not placed(dialog, ROW_GAPS_AFTER)

            controls[ROW_GAP_MODE][1].set("None")
            controls[ROW_GAP_SIZE][1].set("-5")
            controls[ROW_GAPS_AFTER][1].set("0,0")
            dialog.update()
            assert dialog.validate() is True

            controls[ROW_GAP_MODE][1].set("Selected boundaries")
            controls[COLUMN_GAP_MODE][1].set("Selected boundaries")
            controls[ROW_GAP_SIZE][1].set("0.15")
            dialog.update()
            for bad_list in ("2,2", "0", "4", ""):
                controls[ROW_GAPS_AFTER][1].set(bad_list)
                rejected(dialog, ROW_GAPS_AFTER, ROW_GAPS_AFTER)
            controls[ROW_GAPS_AFTER][1].set("2")
            controls[COLUMN_GAPS_AFTER][1].set("2")

            controls[ROW_GAP_SIZE][1].set("-0.25")
            rejected(dialog, ROW_GAP_SIZE, "0 to 2")
            controls[ROW_GAP_SIZE][1].set("0,25")
            controls[COLUMN_GAP_SIZE][1].set("0,5")

            controls[COLUMN_LABEL_FONT_SIZE][1].set(str(10**400))
            rejected(dialog, COLUMN_LABEL_FONT_SIZE, "6 to 36", "window-heatmap-layout-en-error.png")
            controls[COLUMN_LABEL_FONT_SIZE][1].set("abc")
            rejected(dialog, COLUMN_LABEL_FONT_SIZE, "6 to 36")
            controls[COLUMN_LABEL_FONT_SIZE][1].set("")
            reachable(dialog, screen_w, screen_h)
            dialog.fields.select(dialog.fields.tabs()[2])
            dialog.update()
            shot(dialog, "window-heatmap-layout-dialog-en-1024.png")

        edit(mat_idx, validate_and_configure_en)
        pd.testing.assert_frame_equal(app.runs[mat_idx].result.tables["Heat map data"], legacy_matrix_data)
        assert "Heat map layout" in app.runs[mat_idx].result.tables
        poly = poly_collection(mat_idx)
        np.testing.assert_allclose(poly.get_facecolors(), legacy_matrix_rgba, rtol=0, atol=1e-12)
        ax = app.runs[mat_idx].result.figure.axes[0]
        assert ax.get_xlim() == (0.0, 4.5) and ax.get_ylim() == (4.25, 0.0)
        geom = layout_geometry(4, 4, app.runs[mat_idx].options)
        positions = [t.get_position() for t in ax.texts]
        assert (geom["xcenters"][3], geom["ycenters"][2]) in positions
        assert any(t.get_text() == "×" and t.get_position() == (3.0, 0.5) for t in ax.texts)
        assert [t.get_text() for t in ax.get_yticklabels()] == ["r1", "dup", "dup", "$ATP$"]
        app.show("graph", mat_idx)
        root.update()
        shot(root, "window-heatmap-layout-en-1024.png")

        # 4. Top/Right, step 2, Vertical 90, hide one axis, Format Graph & Inspector Apply/Cancel, Transpose/Reverse.
        def configure_axes_and_transforms(dialog):
            controls = dialog.controls
            controls["Transpose"][1].set(True)
            controls["Reverse rows"][1].set(True)
            controls["Reverse columns"][1].set(True)
            controls[SHOW_ROW_LABELS][1].set(False)
            controls[COLUMN_GAP_MODE][1].set("Every boundary")
            controls[COLUMN_GAP_SIZE][1].set("0.5")
            controls[COLUMN_LABEL_FREQUENCY][1].set("Every Nth")
            controls[COLUMN_LABEL_EVERY][1].set("2")
            controls[COLUMN_LABEL_ROTATION][1].set("Vertical")
            controls[COLUMN_LABEL_SIDE][1].set("Top")
            dialog.update()

        edit(mat_idx, configure_axes_and_transforms)
        layout_tbl = app.runs[mat_idx].result.tables["Heat map layout"]
        assert layout_tbl.iloc[0]["Row label"] == "D" and layout_tbl.iloc[0]["Column label"] == "$ATP$"
        ax = app.runs[mat_idx].result.figure.axes[0]
        assert [t for t in ax.get_yticklabels() if t.get_visible()] == []
        xt = [t for t in ax.get_xticklabels() if t.get_visible()]
        assert [t.get_text() for t in xt] == ["$ATP$", "dup"]
        assert [t.get_rotation() for t in xt] == [90.0, 90.0]

        saved_before_style = dict(app.runs[mat_idx].options)
        app.show("graph", mat_idx)
        root.update()
        app.toggle_inspector()
        root.update()
        panel = app.inspector
        panel.vars["title"].set("Inspector Draft")
        panel._now("title")
        panel.cancel()
        root.update()
        assert app.runs[mat_idx].result.figure.axes[0].get_title() == "Heat map"

        app.toggle_inspector()
        root.update()
        panel = app.inspector
        panel.vars["title"].set("Layout Inspected")
        panel._now("title")
        panel.apply()
        root.update()
        assert app.runs[mat_idx].options == saved_before_style
        assert app.runs[mat_idx].result.figure.axes[0].get_ylim() == (4.25, 0.0)
        app.toggle_inspector()
        app.inspector_wanted = False

        def apply_format(dialog):
            dialog.inputs["title"].set("Layout Formatted")

        tools.drive_dialog(tools.GraphFormatDialog, apply_format)
        app.format_graph()
        assert app.runs[mat_idx].result.figure.axes[0].get_title() == "Layout Formatted"
        assert app.runs[mat_idx].options == saved_before_style

        # 5. Long numeric + Long categories with gaps and right row labels.
        app.open_sheet(("graph", long_idx))
        wait()
        edit(long_idx, lambda d: (
            d.controls[ROW_GAP_MODE][1].set("Every boundary"),
            d.controls[ROW_GAP_SIZE][1].set("0.25"),
        ))
        assert "Heat map layout" in app.runs[long_idx].result.tables

        app.open_sheet(("graph", cat_idx))
        wait()
        edit(cat_idx, lambda d: (
            d.controls[ROW_GAP_MODE][1].set("Selected boundaries"),
            d.controls[ROW_GAPS_AFTER][1].set("2"),
            d.controls[ROW_GAP_SIZE][1].set("0.3"),
            d.controls[ROW_LABEL_SIDE][1].set("Right"),
        ))
        cat_ax = app.runs[cat_idx].result.figure.axes[0]
        assert cat_ax.get_ylim() == (3.3, 0.0)
        assert any(t.get_text() == "$ATP$" for t in cat_ax.texts)

        # 6. Worksheet edit reduces categories so selected boundary becomes invalid -> recovery dialog -> Undo.
        app.show("data", "Categories")
        app.current_grid.select((4, 0))
        app.toggle_exclusion()
        wait()
        app.show("data", "Categories")
        app.current_grid.select((5, 0))
        app.toggle_exclusion()
        wait()
        assert app.runs[cat_idx].result is None

        def inspect_recovery(dialog):
            assert dialog.error and "Row gaps after" in dialog.error
            assert dialog.focus_get() is dialog.field_rows[ROW_GAPS_AFTER][1]
            dialog.ok = lambda: None
            dialog.cancel()

        tools.drive_dialog(tools.AnalysisDialog, inspect_recovery)
        app.recalculate(cat_idx)
        wait()
        assert app.runs[cat_idx].result is None
        app.show("data", "Categories")
        app.apply_worksheet_history()
        wait()
        app.show("data", "Categories")
        app.apply_worksheet_history()
        wait()
        assert app.runs[cat_idx].result is not None

        # 7. Italian UI & 1600x1000 screenshot + .alab save in IT -> reopen graph-first in EN.
        if root.winfo_screenwidth() >= 1600 and root.winfo_screenheight() >= 1000:
            root.geometry("1600x1000+0+0")
            root.update()
        hi_w = min(root.winfo_width(), root.winfo_screenwidth())
        hi_h = min(root.winfo_height(), root.winfo_screenheight())
        i18n.set_language("it")

        def configure_it(dialog):
            assert dialog.field_rows[ROW_GAP_MODE][0].cget("text") == "Modalità separazione righe"
            dialog.controls[SHOW_ROW_LABELS][1].set(True)
            dialog.controls[ROW_GAP_MODE][1].set("Selected boundaries")
            dialog.controls[ROW_GAPS_AFTER][1].set("2")
            dialog.controls[ROW_GAP_SIZE][1].set("0,25")
            dialog.controls[ROW_LABEL_FONT_SIZE][1].set("11,5")
            dialog.choice_bindings[ROW_LABEL_SIDE].display.set("Destra")
            reachable(dialog, hi_w, hi_h)
            dialog.fields.select(dialog.fields.tabs()[2])
            dialog.update()
            shot(dialog, "window-heatmap-layout-dialog-it.png")

        edit(mat_idx, configure_it)
        it_recipe = dict(app.runs[mat_idx].options)
        assert it_recipe[ROW_GAP_MODE] == "Selected boundaries"
        assert it_recipe[ROW_GAP_SIZE] == 0.25
        assert it_recipe[ROW_LABEL_SIDE] == "Right"
        assert it_recipe[ROW_LABEL_FONT_SIZE] == 11.5
        app.show("graph", mat_idx)
        root.update()
        shot(root, "window-heatmap-layout-it.png")

        saved_it_path = out / "heatmap-layout-it-saved.alab"
        app.path = saved_it_path
        assert app.save()

        i18n.set_language("en")
        app.import_file(saved_it_path)
        reopened = find_run("Matrix", 0)
        app.open_sheet(("graph", reopened))
        wait()
        assert app.runs[reopened].options == it_recipe

        # 8. Edit cell, exclude, Use Result as Data, CSV/PNG/SVG/PDF & 2-panel layout export.
        app.show("data", "Matrix")
        app.edit_cell(0, 1, "9.5")
        wait()
        app.show("data", "Matrix")
        app.current_grid.select((0, 1))
        app.toggle_exclusion()
        wait()
        app.show("data", "Matrix")
        app.apply_worksheet_history()
        wait()

        app.show("result", reopened)
        root.update()
        tables_before = len(app.tables)
        app.use_result_as_data()
        assert len(app.tables) == tables_before + 1
        csv_target = out / "heatmap-layout-data.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_target)):
            app.export()
        assert csv_target.stat().st_size > 10

        app.show("graph", reopened)
        root.update()
        for ext, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
            target = out / f"heatmap-layout.{ext}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            content = target.read_bytes()
            assert (magic in content[:400] or (ext == "svg" and magic in content)) and len(content) > 1000
        svg_text = (out / "heatmap-layout.svg").read_text(encoding="utf-8")
        assert 'id="PolyCollection_1"' in svg_text and "$ATP$" in svg_text

        reopened_cat = find_run("Categories", 0)
        app.open_sheet(("graph", reopened_cat))
        wait()

        def compose(dialog):
            dialog.name.set("Heat map layout 2-panel")
            dialog.columns.set("2")
            dialog.list.selection_clear(0, "end")
            for number, item in enumerate(dialog.runs):
                if app.runs.index(item) in {reopened, reopened_cat}:
                    dialog.list.selection_set(number)
            dialog.add_selected()

        tools.drive_dialog(tools.LayoutDialog, compose)
        app.new_layout()
        root.update()
        layout_idx = next(i for i, item in enumerate(app.layouts) if item.name == "Heat map layout 2-panel")
        app.show("layout", layout_idx)
        root.update()
        for ext in ("svg", "pdf"):
            target = out / f"heatmap-layout-2panel.{ext}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000
        ET.parse(out / "heatmap-layout-2panel.svg")

        # 9. 80x120 stress run: single aggregated PolyCollection, timing & indicative memory.
        reopened_stress = find_run("Stress80x120", 0)
        tracemalloc.start()
        t0 = time.perf_counter()
        app.open_sheet(("graph", reopened_stress))
        wait()
        elapsed = time.perf_counter() - t0
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        stress_ax = app.runs[reopened_stress].result.figure.axes[0]
        assert len(stress_ax.collections) == 1
        assert isinstance(stress_ax.collections[0], PolyCollection)
        assert len(stress_ax.patches) == 0
        assert len(app.runs[reopened_stress].result.tables["Heat map layout"]) == 80 * 120
        (out / "stress-80x120.json").write_text(
            json.dumps({"elapsed_s": round(elapsed, 4), "peak_mb": round(peak_bytes / (1024 * 1024), 2)}, indent=2) + "\n",
            encoding="utf-8",
        )
        assert not errors, errors
    finally:
        i18n.set_language(original_language)
        if app.inspector is not None:
            app.toggle_inspector()
        app.inspector_wanted = False
        if original_geometry:
            root.geometry(original_geometry)
            root.update()
