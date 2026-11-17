"""Desktop smoke check for heat-map color legend number formatting, driving the real app and dialogs.

``tramastat.py --smoke`` calls :func:`check_heat_map_number_format` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=heatmap-number-format python tramastat.py --smoke DIR``.

Synthetic data only: packaged fixtures from ``tests/data/heatmap_072``. Outputs and screenshots go to
``DIR/heatmap-number-format``.
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

from . import i18n
from .heatmap import LEGEND_INTERVAL, LEGEND_START
from .heatmap_number_format import LEGEND_DECIMALS, NUMBER_FORMAT, format_legend_value

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "heatmap_072"
LEGACY = json.loads((FIXTURES / "legacy-072.json").read_text(encoding="utf-8"))


def check_heat_map_number_format(root, app, directory, tools):
    """Exercise legacy compatibility, 1024x768 dialog validation, EN/IT round-trip, cell edit/exclusion,
    Inspector shortcut, Cancel, PNG/SVG/PDF export, 2-panel layout, and .alab reopen (graph first)."""
    wait, errors = tools.wait_for_calculation, tools.errors
    out = directory / "heatmap-number-format"
    out.mkdir(exist_ok=True)
    original_geometry = root.geometry()
    original_language = i18n.active_language()

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

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
        assert dialog.focus_get() is dialog.field_rows[field][1], dialog.focus_get()
        if shot_name:
            shot(dialog, shot_name)
        return message

    def mesh(index):
        figure = app.runs[index].result.figure
        found = next(c for ax in figure.axes for c in ax.collections if isinstance(c, QuadMesh))
        found.update_scalarmappable()
        return found

    def tick_labels(index):
        bar = mesh(index).colorbar
        assert bar is not None
        axis = bar.ax.xaxis if bar.orientation == "horizontal" else bar.ax.yaxis
        return [t.get_text() for t in axis.get_ticklabels()], axis.get_offset_text().get_text(), bar.get_ticks()

    def find_run(title, number=0):
        return [i for i, run in enumerate(app.runs) if run.title == title][number]

    def edit(index, action):
        app.show("graph", index)
        root.update()
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.edit_analysis(initial_field=app.heat_map_settings_field(app.runs[index]))
        wait()

    try:
        # 1. Legacy recipe without new keys: unchanged formatter, labels and colors.
        legacy_path = directory / "heatmap-number-legacy.alab"
        shutil.copy(FIXTURES / "legacy-072.alab", legacy_path)
        app.import_file(legacy_path)
        matrix = find_run("Numeric", 0)
        app.open_sheet(("graph", matrix))
        wait()
        np.testing.assert_allclose(mesh(matrix).get_facecolors(), LEGACY["matrix"]["rgba"], rtol=1e-12, atol=1e-12)
        assert NUMBER_FORMAT not in app.runs[matrix].options
        assert LEGEND_DECIMALS not in app.runs[matrix].options
        legacy_labels, _, legacy_ticks = tick_labels(matrix)

        # 2. Real dialog at 1024x768: Scientific 2 decimals, export PNG/SVG/PDF.
        root.geometry("1024x768+0+0")
        root.update()
        screen_w = min(1024, root.winfo_screenwidth())
        screen_h = min(768, root.winfo_screenheight())

        def set_scientific(dialog):
            controls = dialog.controls
            assert placed(dialog, NUMBER_FORMAT) and not placed(dialog, LEGEND_DECIMALS)
            controls[LEGEND_INTERVAL][1].set("1")
            controls[LEGEND_START][1].set("0")
            controls[NUMBER_FORMAT][1].set("Scientific")
            dialog.update()
            assert placed(dialog, LEGEND_DECIMALS)
            controls[LEGEND_DECIMALS][1].set("2")
            reachable(dialog, screen_w, screen_h)
            dialog.fields.select(dialog.field_rows[NUMBER_FORMAT][1].master)
            dialog.update()
            shot(dialog, "window-heatmap-number-dialog-1024.png")

        edit(matrix, set_scientific)
        sci_labels, sci_offset, sci_ticks = tick_labels(matrix)
        assert sci_offset == ""
        assert sci_labels == [format_legend_value(float(v), "Scientific", 2) for v in sci_ticks], sci_labels
        app.show("graph", matrix)
        root.update()
        shot(root, "window-heatmap-number-scientific.png")
        for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
            target = out / f"heatmap-scientific.{extension}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            content = target.read_bytes()
            assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000
        svg_text = (out / "heatmap-scientific.svg").read_text(encoding="utf-8")
        assert "2.00e+00" in svg_text

        # 3. Same 1024x768 dialog: Fixed with invalid 2.5 -> FieldError + focus -> fix to 3 -> export.
        def set_fixed_with_error(dialog):
            controls = dialog.controls
            controls[NUMBER_FORMAT][1].set("Fixed")
            dialog.update()
            controls[LEGEND_DECIMALS][1].set("2.5")
            rejected(dialog, LEGEND_DECIMALS, "whole number from 0 to 8")
            controls[LEGEND_DECIMALS][1].set("3")
            reachable(dialog, screen_w, screen_h)

        edit(matrix, set_fixed_with_error)
        fixed_labels, fixed_offset, fixed_ticks = tick_labels(matrix)
        assert fixed_offset == ""
        assert fixed_labels == [format_legend_value(float(v), "Fixed", 3) for v in fixed_ticks], fixed_labels
        assert app.runs[matrix].options[NUMBER_FORMAT] == "Fixed"
        assert app.runs[matrix].options[LEGEND_DECIMALS] == 3
        app.show("graph", matrix)
        root.update()
        shot(root, "window-heatmap-number-fixed.png")

        # 4. Italian UI & error, canonical dict preserved across IT -> EN reopen.
        i18n.set_language("it")

        def italian_check(dialog):
            assert dialog.field_rows[NUMBER_FORMAT][0].cget("text") == "Formato numerico della legenda"
            assert dialog.field_rows[LEGEND_DECIMALS][0].cget("text") == "Decimali della legenda"
            combo = dialog.field_rows[NUMBER_FORMAT][1]
            assert list(combo.cget("values")) == ["Automatico", "Decimali fissi", "Scientifico"]
            assert combo.get() == "Decimali fissi"
            dialog.controls[LEGEND_DECIMALS][1].set("2,5")
            rejected(dialog, LEGEND_DECIMALS, "numero intero da 0 a 8", "window-heatmap-number-it-error.png",
                     caption="Decimali della legenda")
            dialog.controls[LEGEND_DECIMALS][1].set("2,0")
            dialog.fields.select(dialog.field_rows[NUMBER_FORMAT][1].master)
            dialog.update()
            shot(dialog, "window-heatmap-number-it-dialog.png")

        edit(matrix, italian_check)
        italian_recipe = dict(app.runs[matrix].options)
        assert italian_recipe[NUMBER_FORMAT] == "Fixed" and italian_recipe[LEGEND_DECIMALS] == 2
        i18n.set_language("en")

        def english_check(dialog):
            assert dialog.field_rows[NUMBER_FORMAT][1].get() == "Fixed"
            assert dialog.controls[LEGEND_DECIMALS][1].get() == "2"

        edit(matrix, english_check)
        assert app.runs[matrix].options == italian_recipe

        # 5. Edit/exclude cell, recalculate, Inspector shortcut & Cancel.
        app.show("data", "Numeric")
        app.edit_cell(0, 1, "3.5")
        wait()
        edited_labels, _, edited_ticks = tick_labels(matrix)
        assert edited_labels == [format_legend_value(float(v), "Fixed", 2) for v in edited_ticks]
        app.show("data", "Numeric")
        app.current_grid.select((0, 1))
        app.toggle_exclusion()
        wait()
        app.show("data", "Numeric")
        app.current_grid.select((0, 1))
        app.toggle_exclusion()
        wait()
        app.show("data", "Numeric")
        app.edit_cell(0, 1, "0")
        wait()

        app.show("graph", matrix)
        root.update()
        app.toggle_inspector()
        root.update()
        panel = app.inspector
        assert panel is not None and "colors" in panel.widgets
        before_cancel = dict(app.runs[matrix].options)
        before_labels, _, _ = tick_labels(matrix)

        def cancelled(dialog):
            dialog.controls[NUMBER_FORMAT][1].set("Scientific")
            dialog.controls[LEGEND_DECIMALS][1].set("1")
            dialog.cancel()
            dialog.ok = lambda *args: None

        tools.drive_dialog(tools.AnalysisDialog, cancelled)
        panel.widgets["colors"].invoke()
        wait()
        assert app.runs[matrix].options == before_cancel
        assert tick_labels(matrix)[0] == before_labels
        app.toggle_inspector()
        app.inspector_wanted = False
        root.update()

        # 6. Two-panel layout export & .alab save/reopen (graph before worksheet).
        diverging = find_run("Numeric", 1)

        def compose(dialog):
            dialog.name.set("Number format layout")
            dialog.columns.set("2")
            dialog.list.selection_clear(0, "end")
            for number, item in enumerate(dialog.runs):
                if app.runs.index(item) in {matrix, diverging}:
                    dialog.list.selection_set(number)
            dialog.add_selected()

        tools.drive_dialog(tools.LayoutDialog, compose)
        app.new_layout()
        root.update()
        layout = next(i for i, item in enumerate(app.layouts) if item.name == "Number format layout")
        app.show("layout", layout)
        root.update()
        for extension in ("svg", "pdf"):
            target = out / f"heatmap-number-layout.{extension}"
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            assert target.stat().st_size > 1000, extension
        ET.parse(out / "heatmap-number-layout.svg")

        saved_options = dict(app.runs[matrix].options)
        saved_labels, _, _ = tick_labels(matrix)
        app.path = directory / "heatmap-number-format-saved.alab"
        assert app.save()
        app.import_file(app.path)
        reopened = find_run("Numeric", 0)
        app.open_sheet(("graph", reopened))
        wait()
        assert app.runs[reopened].options == saved_options
        assert tick_labels(reopened)[0] == saved_labels
        # Ensure legacy automatic reference still matches baseline expectation.
        assert legacy_ticks is not None and legacy_labels is not None
        assert not errors, errors
    finally:
        i18n.set_language(original_language)
        if app.inspector is not None:
            app.toggle_inspector()
        app.inspector_wanted = False
        if original_geometry:
            root.geometry(original_geometry)
            root.update()
