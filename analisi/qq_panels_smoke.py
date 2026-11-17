"""Desktop smoke check for independent per-panel formatting on Q–Q plots.

``tramastat.py --smoke`` calls :func:`check_qq_panels` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=qq-panels python tramastat.py --smoke DIR``.

Uses synthetic strictly positive data only; outputs and screenshots go to ``DIR/qq-panels``.
"""
import json
import os
import tempfile
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .graph_language_smoke import drive_mapped_dialog
from .normality import DISTRIBUTION, NORMALITY, QQ_LINE, QQ_PLOT, QQ_VARIABLE
from .presentation import apply_style
from .qq_panels import PANEL_KEY, POINTS_ATTR, POINTS_KEY, REFERENCE_ATTR, REFERENCE_KEY, panel_axes


def _find_action_button(root, caption):
    def walk(widget):
        if isinstance(widget, ttk.Button):
            try:
                if str(widget.cget("text")) == caption:
                    return widget
            except Exception:
                pass
        for child in widget.winfo_children():
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(root)


def _action_bar_buttons(root):
    labels = []

    def walk(widget):
        if isinstance(widget, ttk.Button):
            try:
                labels.append(str(widget.cget("text")))
            except Exception:
                pass
        for child in widget.winfo_children():
            walk(child)

    walk(root)
    return labels


def check_qq_panels(root, app, directory, tools):
    """Exercise EN/IT dialogs, inline errors, preview/reset/cancel/apply, Inspector & Format Graph,
    non-Q-Q button hiding, .alab reopen graph-first, edits/exclusions, Both->Normal->Both, SVG/PNG/PDF & layout."""
    wait = tools.wait_for_calculation
    out = directory / "qq-panels"
    out.mkdir(exist_ok=True)
    original_language = i18n.active_language()

    def shot(window, name):
        tools.capture(window, name)
        source = directory / name
        if source.exists():
            source.replace(out / name)

    with tempfile.TemporaryDirectory() as config_tmp:
        env_patch = patch.dict(os.environ, {"APPDATA": config_tmp, "XDG_CONFIG_HOME": config_tmp})
        env_patch.start()
        try:
            i18n.set_language("en")
            frame = pd.DataFrame({
                "Value": [1.1, 1.8, 2.5, 3.4, 4.9, 7.2, 10.5, 15.8, 24.0, 36.0],
                "Extra": [10.0, 12.0, 14.5, 17.0, 20.0, 22.5, 25.0, 28.0, 31.0, 34.5],
            })
            src = out / "qq_source.alab"
            save_project(src, {"Positive": Dataset(frame)})
            app.import_file(src)
            app.show("data", "Positive")

            def choose_qq_both(dialog):
                tools.pick_method(dialog, NORMALITY)
                tools.select_columns(dialog, "Variables", {"Value"})
                dialog.controls[DISTRIBUTION][1].set("Both")
                dialog.controls[QQ_PLOT][1].set(True)
                dialog.controls[QQ_VARIABLE][1].set("Value")
                dialog.controls[QQ_LINE][1].set(True)

            tools.drive_dialog(tools.AnalysisDialog, choose_qq_both)
            app.choose_analysis(only=NORMALITY)
            wait()
            qq_idx = next(i for i, r in enumerate(app.runs) if r.method == NORMALITY)
            app.show("graph", qq_idx)
            root.update()
            screen_w = max(root.winfo_screenwidth(), root.winfo_width())
            screen_h = max(root.winfo_screenheight(), root.winfo_height())

            # Verify action bar shows EN Q–Q panels button.
            assert i18n.tr("qq.panels.button") in _action_bar_buttons(app.page), _action_bar_buttons(app.page)

            # 1) Dialog in EN: reachability, preview on right panel with decimal comma & literal text,
            #    inline errors & focus preservation, reset selected, cancel restore, then apply right panel.
            def test_en_preview_errors_cancel(dialog):
                dialog.update()
                for btn in dialog.buttons.values():
                    assert btn.winfo_viewable()
                    assert btn.winfo_rooty() + btn.winfo_height() <= screen_h, (btn.winfo_rooty(), screen_h)
                    assert btn.winfo_rootx() + btn.winfo_width() <= screen_w, (btn.winfo_rootx(), screen_w)
                assert list(dialog.panel_ids) == ["normal", "lognormal"]
                dialog.panel_binding.display.set(i18n.tr("qq.panels.panel.lognormal"))
                dialog.update()
                dialog.vars["title"].set("Right Preview {A} $x$")
                dialog.vars["xmin"].set("-2,5")
                dialog.vars["xmax"].set("2,5")
                dialog.vars["ymin"].set("-3,0")
                dialog.vars["ymax"].set("3,0")
                dialog.vars["legend_visible"].set(False)
                assert dialog.preview() is True
                shot(dialog, "qq-panels-dialog-en.png")

                # Single limit error keeps previous preview & shows inline message + focus.
                dialog.vars["xmax"].set("")
                assert dialog.preview() is False
                assert "both" in dialog.error_labels["xrange"].cget("text").casefold()
                assert dialog.focus_get() is dialog.widgets["xmax"]
                right_ax = panel_axes(app.runs[qq_idx].result.figure)["lognormal"]
                assert right_ax.get_title() == "Right Preview {A} $x$"
                assert tuple(right_ax.get_xlim()) == (-2.5, 2.5)
                shot(dialog, "qq-panels-error.png")

                # min >= max error.
                dialog.vars["xmin"].set("4")
                dialog.vars["xmax"].set("1")
                assert dialog.preview() is False
                assert "smaller" in dialog.error_labels["xrange"].cget("text").casefold()
                assert dialog.focus_get() is dialog.widgets["xmin"]

                # Reset selected reverts only lognormal, then Cancel reverts everything.
                dialog.reset_selected()
                assert dialog.vars["title"].get() == ""
                dialog.cancel()

            drive_mapped_dialog(root, tools.QQPanelsDialog, test_en_preview_errors_cancel, tools.errors)
            app.edit_qq_panels()
            assert not (app.runs[qq_idx].style or {}).get(PANEL_KEY)

            def apply_en_right(dialog):
                dialog.panel_binding.display.set(i18n.tr("qq.panels.panel.lognormal"))
                dialog.update()
                dialog.vars["title"].set("Lognormal Panel {EN}")
                dialog.vars["xlabel"].set("Log quantiles $z$")
                dialog.vars["ylabel"].set("ln(Value)")
                dialog.vars["xmin"].set("-2,5")
                dialog.vars["xmax"].set("2,5")
                dialog.vars["ymin"].set("-3,0")
                dialog.vars["ymax"].set("3,0")
                dialog.vars["legend_visible"].set(False)

            tools.drive_dialog(tools.QQPanelsDialog, apply_en_right)
            app.edit_qq_panels()
            axes_map = panel_axes(app.runs[qq_idx].result.figure)
            assert axes_map["lognormal"].get_title() == "Lognormal Panel {EN}"
            assert tuple(axes_map["lognormal"].get_xlim()) == (-2.5, 2.5)
            assert axes_map["lognormal"].get_legend() is not None and not axes_map["lognormal"].get_legend().get_visible()
            shot(root, "qq-panels-window-en.png")

            # 2) Switch to Italian: localized action bar button, dialog labels, edit normal panel independently.
            i18n.set_language("it")
            app.show("graph", qq_idx)
            root.update()
            assert i18n.tr("qq.panels.button") in _action_bar_buttons(app.page), _action_bar_buttons(app.page)

            def apply_it_left(dialog):
                assert dialog.buttons["apply"].cget("text") == i18n.tr("qq.panels.apply")
                dialog.vars["title"].set("Pannello Normale {IT}")
                dialog.vars["xlabel"].set("Quantili teorici $x$")
                dialog.vars["ylabel"].set("Valore osservato")
                dialog.vars["xmin"].set("-2,0")
                dialog.vars["xmax"].set("2,0")
                dialog.update()
                shot(dialog, "qq-panels-dialog-it.png")

            tools.drive_dialog(tools.QQPanelsDialog, apply_it_left)
            app.edit_qq_panels()
            axes_map = panel_axes(app.runs[qq_idx].result.figure)
            assert axes_map["normal"].get_title() == "Pannello Normale {IT}"
            assert axes_map["lognormal"].get_title() == "Lognormal Panel {EN}"
            assert tuple(axes_map["normal"].get_xlim()) == (-2.0, 2.0)
            assert tuple(axes_map["lognormal"].get_xlim()) == (-2.5, 2.5)
            shot(root, "qq-panels-both-it.png")

            # 3) Inspector button + settle draft (Yes) + Format Graph preserves qq_panels.
            app.toggle_inspector()
            root.update()
            assert app.inspector is not None and "qq_panels" in app.inspector.widgets
            app.inspector.vars["title"].set("Global Left {Insp}")
            app.inspector._update("title")
            assert app.inspector.has_draft

            def noop_cancel_edit(dialog):
                dialog.vars["ylabel"].set("ln(Y) {Insp}")

            with patch.object(tools.messagebox, "askyesnocancel", return_value=True):
                tools.drive_dialog(tools.QQPanelsDialog, noop_cancel_edit)
                app.edit_qq_panels()
            assert app.runs[qq_idx].style["title"] == "Global Left {Insp}"
            assert app.runs[qq_idx].style[PANEL_KEY]["lognormal"]["title"] == "Lognormal Panel {EN}"
            app.toggle_inspector()  # close inspector

            def drive_format_graph(dialog):
                dialog.inputs["title"].set("Global After Format")

            tools.drive_dialog(tools.GraphFormatDialog, drive_format_graph)
            app.format_graph()
            assert app.runs[qq_idx].style["title"] == "Global After Format"
            assert app.runs[qq_idx].style[PANEL_KEY]["lognormal"]["title"] == "Lognormal Panel {EN}"

            # Restore explicit left panel title for round-trip checks.
            def restore_left_title(dialog):
                dialog.vars["title"].set("Pannello Normale {IT}")

            tools.drive_dialog(tools.QQPanelsDialog, restore_left_title)
            app.edit_qq_panels()

            # 4) Non-Q-Q regression graph (Linear regression): button absent from action bar & Inspector.
            i18n.set_language("en")
            app.show("data", "Positive")

            def choose_xy(dialog):
                tools.pick_method(dialog, "Linear regression")
                dialog.controls["X"][1].set("Extra")
                dialog.controls["Y"][1].set("Value")

            tools.drive_dialog(tools.AnalysisDialog, choose_xy)
            app.choose_analysis()
            wait()
            xy_idx = next(i for i, r in enumerate(app.runs) if r.method == "Linear regression")
            app.show("graph", xy_idx)
            root.update()
            assert not panel_axes(app.runs[xy_idx].result.figure)
            assert i18n.tr("qq.panels.button") not in _action_bar_buttons(app.page)
            app.toggle_inspector()
            root.update()
            assert "qq_panels" not in app.inspector.widgets
            app.toggle_inspector()

            # 5) Save .alab, reopen, open Q–Q graph BEFORE opening results.
            saved_path = out / "qq-panels-roundtrip.alab"
            app.path = saved_path
            assert app.save()
            app.import_file(saved_path)
            qq_reopened = next(i for i, r in enumerate(app.runs) if r.method == NORMALITY)
            assert qq_reopened is not None
            app.show("graph", qq_reopened)
            if app.runs[qq_reopened].result is None:
                app.recalculate(qq_reopened)
                wait()
            reopened_axes = panel_axes(app.runs[qq_reopened].result.figure)
            assert reopened_axes["normal"].get_title() == "Pannello Normale {IT}"
            assert reopened_axes["lognormal"].get_title() == "Lognormal Panel {EN}"
            assert tuple(reopened_axes["normal"].get_xlim()) == (-2.0, 2.0)
            assert tuple(reopened_axes["lognormal"].get_xlim()) == (-2.5, 2.5)
            assert not reopened_axes["lognormal"].get_legend().get_visible()
            shot(root, "qq-panels-reopened.png")

            # 6) Exclusion and cell edit recalculation keep per-panel formatting.
            app.show("data", "Positive")
            app.current_grid.active_cell = (1, 0)
            app.toggle_exclusion()
            wait()
            app.edit_cell(2, 0, "3.9")
            wait()
            app.show("graph", qq_reopened)
            root.update()
            edited_axes = panel_axes(app.runs[qq_reopened].result.figure)
            assert edited_axes["normal"].get_title() == "Pannello Normale {IT}"
            assert edited_axes["lognormal"].get_title() == "Lognormal Panel {EN}"
            assert tuple(edited_axes["lognormal"].get_xlim()) == (-2.5, 2.5)

            # 7) Mode transition Both -> Normal -> Both keeps inactive lognormal override intact.
            def set_mode(mode):
                def _edit(dialog):
                    dialog.controls[DISTRIBUTION][1].set(mode)
                return _edit

            tools.drive_dialog(tools.AnalysisDialog, set_mode("Normal"))
            app.edit_analysis()
            wait()
            only_normal = panel_axes(app.runs[qq_reopened].result.figure)
            assert list(only_normal) == ["normal"]
            assert only_normal["normal"].get_title() == "Pannello Normale {IT}"
            assert app.runs[qq_reopened].style[PANEL_KEY]["lognormal"]["title"] == "Lognormal Panel {EN}"

            tools.drive_dialog(tools.AnalysisDialog, set_mode("Both"))
            app.edit_analysis()
            wait()
            restored_both = panel_axes(app.runs[qq_reopened].result.figure)
            assert list(restored_both) == ["normal", "lognormal"]
            assert restored_both["lognormal"].get_title() == "Lognormal Panel {EN}"
            assert tuple(restored_both["lognormal"].get_xlim()) == (-2.5, 2.5)

            # 8) Export PNG/SVG/PDF of the Q–Q graph and a 2-graph Layout (Q–Q Both + XY).
            app.show("graph", qq_reopened)
            root.update()
            for ext, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
                target = out / f"qq-panels.{ext}"
                with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                    app.export()
                content = target.read_bytes()
                assert (magic in content[:400] or (ext == "svg" and magic in content)) and len(content) > 1000
            ET.parse(out / "qq-panels.svg")

            xy_reopened = next(i for i, r in enumerate(app.runs) if r.method == "Linear regression")
            app.open_sheet(("graph", xy_reopened))
            wait()

            def compose_layout(dialog):
                dialog.name.set("QQ 2-graph layout")
                dialog.columns.set("2")
                dialog.list.selection_clear(0, "end")
                for idx_item, item in enumerate(dialog.runs):
                    if app.runs.index(item) in {qq_reopened, xy_reopened}:
                        dialog.list.selection_set(idx_item)
                dialog.add_selected()

            tools.drive_dialog(tools.LayoutDialog, compose_layout)
            app.new_layout()
            root.update()
            layout_idx = next(i for i, item in enumerate(app.layouts) if item.name == "QQ 2-graph layout")
            app.show("layout", layout_idx)
            root.update()
            for ext in ("svg", "pdf"):
                target = out / f"qq-panels-layout.{ext}"
                with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                    app.export()
                assert target.stat().st_size > 1000
            ET.parse(out / "qq-panels-layout.svg")

            assert not tools.errors, tools.errors
            (out / "checks.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "screen": [screen_w, screen_h],
                        "checks": [
                            "EN/IT dialog & action bar",
                            "preview/reset/cancel/apply",
                            "inline errors & focus",
                            "Inspector & Format Graph preservation",
                            "hidden on non-Q-Q graph",
                            ".alab graph-first round-trip",
                            "exclusion & edit recalculation",
                            "Both->Normal->Both preservation",
                            "PNG/SVG/PDF & Layout exports",
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            if app.inspector is not None:
                app.toggle_inspector()
                root.update()
            i18n.set_language(original_language)
            env_patch.stop()


def check_qq_artist_styles(root, app, directory, tools):
    """Desktop smoke check for independent per-panel Q–Q point & reference line styles.

    Invoked by ``TRAMASTAT_SMOKE_ONLY=qq-artist-styles`` and during full smoke.
    """
    from tkinter import colorchooser
    from matplotlib.colors import to_rgba
    from matplotlib.markers import MarkerStyle

    wait = tools.wait_for_calculation
    out = directory / "qq-artist-styles"
    out.mkdir(exist_ok=True)
    original_language = i18n.active_language()

    def shot(window, name):
        tools.capture(window, name)
        source = directory / name
        if source.exists():
            source.replace(out / name)

    with tempfile.TemporaryDirectory() as config_tmp:
        env_patch = patch.dict(os.environ, {"APPDATA": config_tmp, "XDG_CONFIG_HOME": config_tmp})
        env_patch.start()
        try:
            i18n.set_language("en")
            frame = pd.DataFrame({
                "A": [1.2, 2.1, 3.3, 4.8, 6.7, 9.5, 13.8, 19.6],
                "B": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0],
            })
            src = out / "qq_artists_source.alab"
            save_project(src, {"Positive": Dataset(frame)})
            app.import_file(src)
            app.show("data", "Positive")

            # Run 1: Both Q–Q plots with reference line; Run 2: Legacy Q–Q without reference line; Run 3: XY.
            def choose_both(dialog):
                tools.pick_method(dialog, NORMALITY)
                tools.select_columns(dialog, "Variables", {"A"})
                dialog.controls[DISTRIBUTION][1].set("Both")
                dialog.controls[QQ_PLOT][1].set(True)
                dialog.controls[QQ_VARIABLE][1].set("A")
                dialog.controls[QQ_LINE][1].set(True)

            tools.drive_dialog(tools.AnalysisDialog, choose_both)
            app.choose_analysis(only=NORMALITY)
            wait()

            def choose_legacy_no_line(dialog):
                tools.pick_method(dialog, NORMALITY)
                tools.select_columns(dialog, "Variables", {"A"})
                dialog.controls[DISTRIBUTION][1].set("Normal")
                dialog.controls[QQ_PLOT][1].set(True)
                dialog.controls[QQ_VARIABLE][1].set("A")
                dialog.controls[QQ_LINE][1].set(False)

            tools.drive_dialog(tools.AnalysisDialog, choose_legacy_no_line)
            app.choose_analysis(only=NORMALITY)
            wait()

            def choose_xy(dialog):
                tools.pick_method(dialog, "Linear regression")
                dialog.controls["X"][1].set("B")
                dialog.controls["Y"][1].set("A")

            tools.drive_dialog(tools.AnalysisDialog, choose_xy)
            app.choose_analysis()
            wait()

            qq_idx = next(i for i, r in enumerate(app.runs) if r.method == NORMALITY and r.options.get(DISTRIBUTION) == "Both")
            legacy_idx = next(i for i, r in enumerate(app.runs) if r.method == NORMALITY and r.options.get(DISTRIBUTION) == "Normal")
            xy_idx = next(i for i, r in enumerate(app.runs) if r.method == "Linear regression")

            app.show("graph", qq_idx)
            root.update()
            screen_w = max(root.winfo_screenwidth(), root.winfo_width())
            screen_h = max(root.winfo_screenheight(), root.winfo_height())

            # 1) Open from Graph toolbar button: test inline error, fix, preview, and Cancel restore.
            toolbar_btn = _find_action_button(app.page, i18n.tr("qq.panels.button"))
            assert toolbar_btn is not None
            orig_pts_sizes = getattr(panel_axes(app.runs[qq_idx].result.figure)["normal"], POINTS_ATTR).get_sizes().copy()

            def test_error_and_cancel(dialog):
                dialog.update()
                for btn in dialog.buttons.values():
                    assert btn.winfo_viewable()
                    assert btn.winfo_rooty() + btn.winfo_height() <= screen_h
                    assert btn.winfo_rootx() + btn.winfo_width() <= screen_w

                dialog.notebook.select(dialog.tabs["points"])
                dialog.marker_binding.display.set(i18n.tr("graph.marker.square"))
                dialog.vars["points_size"].set("7,0")
                dialog.vars["points_color"].set("#127A78")
                dialog.vars["points_alpha"].set("0,65")
                assert dialog.preview() is True
                shot(dialog, "qq-artist-dialog-en.png")

                # Trigger error on points_size -> tab stays on points & focus moves to points_size.
                dialog.notebook.select(dialog.tabs["axes"])
                dialog.vars["points_size"].set("40")
                assert dialog.preview() is False
                assert dialog.notebook.select() == str(dialog.tabs["points"])
                assert dialog.focus_get() is dialog.widgets["points_size"]
                # Last valid preview size=7 -> area 49 remains on figure.
                pts = getattr(panel_axes(app.runs[qq_idx].result.figure)["normal"], POINTS_ATTR)
                np.testing.assert_allclose(pts.get_sizes(), [49.0])
                shot(dialog, "qq-artist-error.png")

                # Correct error and Cancel -> reverts to confirmed default area 26.
                dialog.vars["points_size"].set("7,0")
                dialog.cancel()

            drive_mapped_dialog(root, tools.QQPanelsDialog, test_error_and_cancel, tools.errors)
            toolbar_btn.invoke()
            np.testing.assert_allclose(
                getattr(panel_axes(app.runs[qq_idx].result.figure)["normal"], POINTS_ATTR).get_sizes(),
                orig_pts_sizes,
            )
            assert not app.runs[qq_idx].style

            # 2) Open from Inspector button: apply independent styles on normal and lognormal.
            app.toggle_inspector()
            root.update()
            assert app.inspector is not None and "qq_panels" in app.inspector.widgets

            def apply_en_from_inspector(dialog):
                dialog.panel_binding.display.set(i18n.tr("qq.panels.panel.normal"))
                dialog.update()
                dialog.notebook.select(dialog.tabs["points"])
                dialog.marker_binding.display.set(i18n.tr("graph.marker.square"))
                dialog.vars["points_size"].set("7,0")
                with patch.object(colorchooser, "askcolor", return_value=((18, 122, 120), "#127A78")):
                    dialog.pickers["points_color"].invoke()
                dialog.vars["points_alpha"].set("0,65")
                dialog.notebook.select(dialog.tabs["reference"])
                dialog.vars["ref_color"].set("#D1553A")
                dialog.vars["ref_width"].set("2,0")
                dialog.ref_style_binding.display.set(i18n.tr("graph.line.dashed"))
                dialog.vars["ref_alpha"].set("0,8")

                dialog.panel_binding.display.set(i18n.tr("qq.panels.panel.lognormal"))
                dialog.update()
                dialog.notebook.select(dialog.tabs["points"])
                dialog.marker_binding.display.set(i18n.tr("graph.marker.diamond"))
                dialog.vars["points_size"].set("4,0")
                dialog.vars["points_color"].set("#7030A0")
                dialog.notebook.select(dialog.tabs["reference"])
                dialog.vars["ref_visible"].set(False)
                dialog._sync_artist_controls()

            tools.drive_dialog(tools.QQPanelsDialog, apply_en_from_inspector)
            app.inspector.widgets["qq_panels"].invoke()
            axes_map = panel_axes(app.runs[qq_idx].result.figure)
            n_pts = getattr(axes_map["normal"], POINTS_ATTR)
            n_ref = getattr(axes_map["normal"], REFERENCE_ATTR)
            l_ref = getattr(axes_map["lognormal"], REFERENCE_ATTR)
            np.testing.assert_allclose(n_pts.get_sizes(), [49.0])
            np.testing.assert_allclose(n_pts.get_facecolors()[0], to_rgba("#127A78", 0.65))
            assert n_ref.get_linestyle() == "--" and n_ref.get_linewidth() == 2.0 and not l_ref.get_visible()
            assert [t.get_text() for t in axes_map["lognormal"].get_legend().get_texts()] == ["Observed values"]
            shot(root, "qq-artist-window-en.png")

            # Inspector draft Cancel preserves confirmed qq_panels; Inspector Apply preserves qq_panels.
            app.inspector.vars["title"].set("Inspector Cancel Draft")
            app.inspector._update("title")
            app.inspector.cancel()
            assert app.runs[qq_idx].style[PANEL_KEY]["normal"][POINTS_KEY]["marker"] == "s"
            app.toggle_inspector()
            root.update()
            app.inspector.vars["title"].set("Global Inspected Title")
            app.inspector._update("title")
            app.inspector.apply()
            assert app.runs[qq_idx].style["title"] == "Global Inspected Title"
            assert app.runs[qq_idx].style[PANEL_KEY]["lognormal"][REFERENCE_KEY]["visible"] is False
            if app.inspector is not None:
                app.toggle_inspector()
                root.update()

            # Format Graph Reset preserves qq_panels!
            def drive_reset(dialog):
                dialog._reset()

            drive_mapped_dialog(root, tools.GraphFormatDialog, drive_reset, tools.errors)
            app.format_graph()
            assert "title" not in (app.runs[qq_idx].style or {})
            assert app.runs[qq_idx].style[PANEL_KEY]["normal"][POINTS_KEY]["color"] == "#127A78"

            # Add native annotation & shape alongside Q–Q artist styles.
            import uuid
            with_ann = dict(app.runs[qq_idx].style)
            with_ann["annotations"] = [
                {"text": "Note", "position": [0.2, 0.8], "units": "axes", "align": "left", "size": 10, "color": "#112233"}
            ]
            with_ann["shapes"] = [
                {
                    "id": str(uuid.uuid4()), "kind": "rectangle", "units": "axes",
                    "points": [[0.15, 0.15], [0.45, 0.45]], "stroke": "#334455",
                    "width": 1.2, "line_style": "dashed", "fill": None, "alpha": 0.9, "layer": "above",
                }
            ]
            apply_style(app.runs[qq_idx].result.figure, with_ann)
            app.commit_graph_style(app.runs[qq_idx], with_ann, record_shapes=False)
            app.graph_canvas.draw_idle()
            root.update()
            assert len(getattr(axes_map["normal"], "_tramastat_annotations", ())) == 1
            assert len(getattr(axes_map["normal"], "_tramastat_shapes", ())) == 1
            np.testing.assert_allclose(getattr(axes_map["normal"], POINTS_ATTR).get_sizes(), [49.0])

            # 3) Switch to Italian: inspect controls, disabled state without clearing values, Apply canonical JSON.
            i18n.set_language("it")
            app.show("graph", qq_idx)
            root.update()

            def inspect_and_apply_it(dialog):
                assert [dialog.notebook.tab(i, "text") for i in range(3)] == [
                    "Assi e titolo", "Punti", "Retta di riferimento"
                ]
                dialog.notebook.select(dialog.tabs["points"])
                dialog.vars["points_visible"].set(False)
                dialog._sync_artist_controls()
                assert str(dialog.widgets["points_size"].cget("state")) == "disabled"
                assert dialog.vars["points_size"].get() == "7.0"
                dialog.vars["points_visible"].set(True)
                dialog._sync_artist_controls()
                dialog.marker_binding.display.set("Croce")
                dialog.update()
                shot(dialog, "qq-artist-dialog-it.png")

            tools.drive_dialog(tools.QQPanelsDialog, inspect_and_apply_it)
            app.edit_qq_panels()
            assert app.runs[qq_idx].style[PANEL_KEY]["normal"][POINTS_KEY]["marker"] == "x"
            shot(root, "qq-artist-styled-it.png")

            # Unavailable line check on legacy run (show_line=False).
            app.show("graph", legacy_idx)
            root.update()
            assert getattr(panel_axes(app.runs[legacy_idx].result.figure)["normal"], REFERENCE_ATTR) is None

            def check_unavail(dialog):
                dialog.notebook.select(dialog.tabs["reference"])
                dialog.update()
                assert str(dialog.widgets["ref_visible"].cget("state")) == "disabled"
                assert dialog.ref_unavailable_label.winfo_viewable()
                dialog.cancel()

            drive_mapped_dialog(root, tools.QQPanelsDialog, check_unavail, tools.errors)
            app.edit_qq_panels()
            assert len(panel_axes(app.runs[legacy_idx].result.figure)["normal"].lines) == 0

            # 4) Save .alab, reopen, source edit, recalculate, legacy preservation, PNG/SVG/PDF & 2-panel Layout.
            saved = out / "qq-artist-roundtrip.alab"
            app.path = saved
            assert app.save()
            app.import_file(saved)

            reopened_qq = next(i for i, r in enumerate(app.runs) if r.method == NORMALITY and r.options.get(DISTRIBUTION) == "Both")
            reopened_legacy = next(i for i, r in enumerate(app.runs) if r.method == NORMALITY and r.options.get(DISTRIBUTION) == "Normal")
            reopened_xy = next(i for i, r in enumerate(app.runs) if r.method == "Linear regression")

            app.show("graph", reopened_qq)
            if app.runs[reopened_qq].result is None:
                app.recalculate(reopened_qq)
                wait()
            re_ax = panel_axes(app.runs[reopened_qq].result.figure)
            re_pts = getattr(re_ax["normal"], POINTS_ATTR)
            expected_path = MarkerStyle("x").get_path().transformed(MarkerStyle("x").get_transform())
            np.testing.assert_allclose(re_pts.get_paths()[0].vertices, expected_path.vertices)
            np.testing.assert_allclose(re_pts.get_sizes(), [49.0])

            # Modify source cell -> recalculate keeps styles while updating data coordinates.
            old_offsets = re_pts.get_offsets().copy()
            app.show("data", "Positive")
            app.edit_cell(2, 0, "4.2")
            wait()
            app.show("graph", reopened_qq)
            root.update()
            new_ax = panel_axes(app.runs[reopened_qq].result.figure)
            new_pts = getattr(new_ax["normal"], POINTS_ATTR)
            np.testing.assert_allclose(new_pts.get_sizes(), [49.0])
            assert not np.array_equal(new_pts.get_offsets(), old_offsets)

            # Export PNG, vector SVG (no embedded raster <image), PDF.
            for ext, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
                target = out / f"qq-artist.{ext}"
                with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                    app.export()
                raw_bytes = target.read_bytes()
                assert (magic in raw_bytes[:400] or (ext == "svg" and magic in raw_bytes)) and len(raw_bytes) > 1000
            svg_text = (out / "qq-artist.svg").read_text(encoding="utf-8")
            assert "<image" not in svg_text
            ET.fromstring(svg_text)

            # Open legacy & XY and build 2-panel layout export.
            app.open_sheet(("graph", reopened_legacy))
            wait()
            app.open_sheet(("graph", reopened_xy))
            wait()

            def compose_artist_layout(dialog):
                dialog.name.set("QQ artist layout")
                dialog.columns.set("2")
                dialog.list.selection_clear(0, "end")
                for idx_item, item in enumerate(dialog.runs):
                    if app.runs.index(item) in {reopened_qq, reopened_xy}:
                        dialog.list.selection_set(idx_item)
                dialog.add_selected()

            tools.drive_dialog(tools.LayoutDialog, compose_artist_layout)
            app.new_layout()
            root.update()
            layout_idx = next(i for i, item in enumerate(app.layouts) if item.name == "QQ artist layout")
            app.show("layout", layout_idx)
            root.update()
            for ext in ("svg", "pdf"):
                target = out / f"qq-artist-layout.{ext}"
                with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                    app.export()
                assert target.stat().st_size > 1000
            ET.parse(out / "qq-artist-layout.svg")

            assert not tools.errors, tools.errors
            (out / "checks.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "screen": [screen_w, screen_h],
                        "checks": [
                            "toolbar & Inspector launch",
                            "EN/IT ChoiceBinding, swatch/picker & decimal comma",
                            "inline errors, tab switch & focus",
                            "dependency disable without clearing",
                            "unavailable reference line explanation",
                            "Format Graph Reset, Inspector Apply/Cancel & native shapes/annotations",
                            ".alab round-trip & source edit recalc",
                            "legacy preservation & vector SVG/PDF/PNG & 2-panel layout",
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            if app.inspector is not None:
                app.toggle_inspector()
                root.update()
            i18n.set_language(original_language)
            env_patch.stop()
