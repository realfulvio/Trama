"""Desktop smoke check for composition segment styles (pie, donut, bars and dot plot).

``tramastat.py --smoke`` (or ``TRAMASTAT_SMOKE_ONLY=composition-styles`` /
``TRAMASTAT_SMOKE_ONLY=parts-styles``) calls :func:`check_parts_segment_styles`.
"""
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from matplotlib.patches import Wedge

from . import parts_style_dialog as style_dialogs
from .data import Dataset, save_project
from .parts_of_whole import (APPLY_SEGMENT_STYLES, BORDER_COLOR, BORDER_WIDTH, DONUT, DOTS,
                             HORIZONTAL, PARTS_GRAPH, SEGMENT_STYLES, SLICE_LABELS, START_ANGLE, VERTICAL)
from .parts_style_dialog import PartsStyleDialog


def _find(parent, kind):
    for child in parent.winfo_children():
        if isinstance(child, kind):
            return child
        found = _find(child, kind)
        if found is not None:
            return found
    return None


def _wedges(figure):
    return [patch for patch in figure.axes[0].patches if isinstance(patch, Wedge)]


def check_parts_segment_styles(root, app, directory, kit):
    from tkinter import filedialog

    capture, drive, pick, wait = kit.capture, kit.drive_dialog, kit.pick_method, kit.wait_for_calculation
    path = directory / "segment-styles.alab"
    title = "Composition"
    frame = pd.DataFrame({"Category": ["A", "A", "Zero", "B", "Blank"], "Value": [1, 1, 0, 2, None]})
    save_project(path, {title: Dataset(frame)})
    app.import_file(path)

    notices = []

    def record_error(*args, **kwargs):
        notices.append(args[1] if len(args) > 1 else args)
        return "ok"

    def guarded(script):
        def run():
            child = _find(root, PartsStyleDialog)
            try:
                if child is None:
                    raise AssertionError("segment editor did not open")
                script(child)
            except Exception:
                (directory / "callback-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                if child is not None and child.winfo_exists():
                    child.cancel()
        root.after(200, run)

    def configure(dialog):
        pick(dialog, PARTS_GRAPH)
        dialog.controls["Values"][1].set("Value")
        dialog.controls["Row titles"][1].set("Category")
        dialog.controls["Graph style"][1].set(DONUT)
        assert dialog.field_rows[START_ANGLE][1].grid_info()
        assert dialog.field_rows[SEGMENT_STYLES][1].grid_info()
        for non_pie in (HORIZONTAL, VERTICAL, DOTS):
            dialog.controls["Graph style"][1].set(non_pie)
            assert not dialog.field_rows[START_ANGLE][1].grid_info()
            assert dialog.field_rows[SEGMENT_STYLES][1].grid_info()
        dialog.controls["Graph style"][1].set(DONUT)
        assert dialog.field_rows[SEGMENT_STYLES][1].grid_info()

        def invalid_explode(child):
            assert child.explode_entry.winfo_manager() == "grid"
            child.explode.set("0.7")
            original = style_dialogs.messagebox.showerror
            style_dialogs.messagebox.showerror = record_error
            try:
                assert child.validate() is False
            finally:
                style_dialogs.messagebox.showerror = original
            message = notices[-1]
            assert "Row 1" in message and "explode" in message, message
            assert child.error_widget is child.explode_entry
            assert child.winfo_exists()
            capture(child, "window-parts-invalid-explode.png")
            child.cancel()

        guarded(invalid_explode)
        dialog.edit_segment_styles()
        assert dialog.segment_styles == {}
        assert dialog.apply_segment_styles is False
        assert not (directory / "callback-error.txt").exists(), (directory / "callback-error.txt").read_text()

        def accept_donut(child):
            child.color.set("#d62728")
            child.explode.set("0.12")
            child.listbox.selection_clear(0, "end")
            child.listbox.selection_set(1)
            child._changed()
            child.color.set("#2ca02c")
            child.visible.set(False)
            child.listbox.selection_clear(0, "end")
            child.listbox.selection_set(3)
            child._changed()
            child.color.set("#1f77b4")
            capture(child, "window-parts-editor.png")
            child.ok()

        guarded(accept_donut)
        dialog.edit_segment_styles()
        assert not (directory / "callback-error.txt").exists(), (directory / "callback-error.txt").read_text()
        assert dialog.segment_styles["row:1"]["color"] == "#d62728"
        assert dialog.segment_styles["row:1"]["explode"] == 0.12
        assert dialog.segment_styles["row:2"]["visible"] is False
        assert dialog.segment_styles["row:4"]["color"] == "#1f77b4"
        assert dialog.apply_segment_styles is True
        dialog.controls[SLICE_LABELS][1].set("Percent")
        dialog.controls[BORDER_COLOR][1].set("#394c60")
        dialog.controls[BORDER_WIDTH][1].set("2")
        capture(dialog, "window-parts-options.png")

    drive(configure)
    app.choose_analysis()
    wait()
    run = app.runs[0]
    drawn = _wedges(run.result.figure)
    assert [item.get_visible() for item in drawn] == [True, False, True]
    np.testing.assert_allclose(drawn[0].get_facecolor(), to_rgba("#d62728"))
    np.testing.assert_allclose(drawn[2].get_facecolor(), to_rgba("#1f77b4"))
    assert [text.get_text() for text in run.result.figure.axes[0].texts].count("25.0%") == 1
    app.show("graph", 0)
    capture(root, "window-parts-donut-styles.png")

    # Switch to Horizontal slices, test Cancel vs OK, invalid color error & fix, and hidden Explode
    def configure_horizontal(dialog):
        dialog.controls["Graph style"][1].set(HORIZONTAL)
        assert dialog.field_rows[SEGMENT_STYLES][1].grid_info()

        def cancel_bar_edit(child):
            assert child.explode_entry.winfo_manager() == ""
            assert child.explode_label.winfo_manager() == ""
            child.color.set("#000000")
            child.cancel()

        guarded(cancel_bar_edit)
        dialog.edit_segment_styles()
        assert not (directory / "callback-error.txt").exists(), (directory / "callback-error.txt").read_text()
        assert dialog.segment_styles["row:1"]["color"] == "#d62728"

        def edit_bar_styles(child):
            child.update_idletasks()
            assert child.winfo_width() <= 1024 and child.winfo_height() <= 768
            assert child.explode_entry.winfo_manager() == ""
            child.color.set("not-a-color")
            original = style_dialogs.messagebox.showerror
            style_dialogs.messagebox.showerror = record_error
            try:
                assert child.validate() is False
            finally:
                style_dialogs.messagebox.showerror = original
            message = notices[-1]
            assert "Row 1" in message and "color" in message, message
            assert child.error_widget is child.color_entry
            assert child.winfo_exists()

            child.color.set("#c0392b")
            child.listbox.selection_clear(0, "end")
            child.listbox.selection_set(1)
            child._changed()
            child.color.set("#1f7a8c")
            child.visible.set(False)
            child.listbox.selection_clear(0, "end")
            child.listbox.selection_set(3)
            child._changed()
            child.color.set("#2e8b57")
            child.visible.set(True)
            capture(child, "window-composition-segment-dialog.png")
            child.ok()

        guarded(edit_bar_styles)
        dialog.edit_segment_styles()
        assert not (directory / "callback-error.txt").exists(), (directory / "callback-error.txt").read_text()
        assert dialog.apply_segment_styles is True
        # Explode from the pie configuration is preserved in Segment styles
        assert dialog.segment_styles["row:1"]["explode"] == 0.12
        assert dialog.segment_styles["row:1"]["color"] == "#c0392b"

    app.show("graph", 0)
    drive(configure_horizontal)
    app.edit_analysis()
    wait()
    horiz_run = app.runs[0]
    assert horiz_run.options[APPLY_SEGMENT_STYLES] is True
    assert horiz_run.options[SEGMENT_STYLES]["row:1"]["explode"] == 0.12
    horiz_patches = horiz_run.result.figure.axes[0].patches
    assert [p.get_visible() for p in horiz_patches] == [True, False, True]
    np.testing.assert_allclose([p.get_x() for p in horiz_patches], [0.0, 0.25, 0.5])
    np.testing.assert_allclose([p.get_width() for p in horiz_patches], [0.25, 0.25, 0.5])
    np.testing.assert_allclose(horiz_patches[0].get_facecolor(), to_rgba("#c0392b"))
    np.testing.assert_allclose(horiz_patches[2].get_facecolor(), to_rgba("#2e8b57"))
    app.show("graph", 0)
    capture(root, "window-composition-segment-graph.png")

    # Switch to Vertical slices and verify vertical bar geometry and styles
    def configure_vertical(dialog):
        dialog.controls["Graph style"][1].set(VERTICAL)

    drive(configure_vertical)
    app.edit_analysis()
    wait()
    vert_patches = app.runs[0].result.figure.axes[0].patches
    assert [p.get_visible() for p in vert_patches] == [True, False, True]
    np.testing.assert_allclose([p.get_y() for p in vert_patches], [0.0, 0.25, 0.5])
    np.testing.assert_allclose([p.get_height() for p in vert_patches], [0.25, 0.25, 0.5])
    np.testing.assert_allclose(vert_patches[0].get_facecolor(), to_rgba("#c0392b"))
    np.testing.assert_allclose(vert_patches[2].get_facecolor(), to_rgba("#2e8b57"))

    # Switch to Dot plot and verify dot allocations and styles
    def configure_dots(dialog):
        dialog.controls["Graph style"][1].set(DOTS)
        dialog.controls["Number of dots"][1].set("20")

        def verify_dots_dialog(child):
            assert child.explode_entry.winfo_manager() == ""
            child.ok()

        guarded(verify_dots_dialog)
        dialog.edit_segment_styles()
        assert not (directory / "callback-error.txt").exists(), (directory / "callback-error.txt").read_text()

    drive(configure_dots)
    app.edit_analysis()
    wait()
    dot_cols = app.runs[0].result.figure.axes[0].collections
    assert [col.get_visible() for col in dot_cols] == [True, False, True]
    assert [len(col.get_offsets()) for col in dot_cols] == [5, 5, 10]
    np.testing.assert_allclose(dot_cols[0].get_facecolor()[0], to_rgba("#c0392b"))
    np.testing.assert_allclose(dot_cols[2].get_facecolor()[0], to_rgba("#2e8b57"))

    # Round-trip back to Donut (pie -> bar -> pie) and verify explode was preserved
    def configure_back_to_donut(dialog):
        dialog.controls["Graph style"][1].set(DONUT)

    drive(configure_back_to_donut)
    app.edit_analysis()
    wait()
    donut_again = _wedges(app.runs[0].result.figure)
    assert app.runs[0].options[SEGMENT_STYLES]["row:1"]["explode"] == 0.12
    np.testing.assert_allclose(
        donut_again[0].center, np.array([np.cos(np.pi / 4), np.sin(np.pi / 4)]) * 0.12, atol=1e-7
    )

    # Return to Horizontal slices for .alab save/reopen, cell edit, exclusion, Use Result as Data and export
    def configure_back_to_horiz(dialog):
        dialog.controls["Graph style"][1].set(HORIZONTAL)

    drive(configure_back_to_horiz)
    app.edit_analysis()
    wait()

    assert app.save()
    app.import_file(app.path)
    app.open_sheet(("graph", 0))
    wait()
    reopened = app.runs[0]
    assert reopened.options[APPLY_SEGMENT_STYLES] is True
    assert reopened.options[SEGMENT_STYLES]["row:1"]["explode"] == 0.12
    np.testing.assert_allclose(reopened.result.figure.axes[0].patches[0].get_facecolor(), to_rgba("#c0392b"))

    app.show("data", title)
    app.edit_cell(0, 0, "Alpha")
    wait()
    assert app.runs[0].result.tables["Composition"]["Category"].iloc[0] == "Alpha"
    assert np.allclose(app.runs[0].result.figure.axes[0].patches[0].get_facecolor(), to_rgba("#c0392b"))
    app.show("data", title)
    app.current_grid.select((0, 1))
    app.toggle_exclusion()
    wait()
    after = app.runs[0].result.figure.axes[0].patches
    assert [item.get_visible() for item in after] == [False, True]
    np.testing.assert_allclose(after[1].get_facecolor(), to_rgba("#2e8b57"))
    assert app.runs[0].options[SEGMENT_STYLES]["row:1"]["color"] == "#c0392b"

    # Use Result as Data on Composition result sheet
    app.show("result", 0)
    root.update()
    before_tables = set(app.tables)
    app.use_result_as_data()
    new_tables = set(app.tables) - before_tables
    assert len(new_tables) == 1
    derived_name = next(iter(new_tables))
    assert list(app.tables[derived_name].frame().columns) == ["Category", "Value", "Fraction", "Percent"]

    app.show("graph", 0)
    png_path = directory / "segment-styles.png"
    svg_path = directory / "segment-styles.svg"
    with patch.object(filedialog, "asksaveasfilename", return_value=str(png_path)):
        app.export()
    with patch.object(filedialog, "asksaveasfilename", return_value=str(svg_path)):
        app.export()
    assert png_path.stat().st_size > 1000
    assert b"<svg" in svg_path.read_bytes()
