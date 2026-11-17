"""Desktop smoke check for the 0.72 heat-map colors and legends, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_heat_map_colors` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=heatmap-colors python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/heatmap_072). The expected colors come from the independent
standard-library oracle (tests/heatmap_color_oracle.py), not from the module under test. Screenshots and exports go
to ``DIR/heatmap-colors``.
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
from .figure_export_dialog import FigureExportDialog
from .heatmap import (CATEGORY_COLORS, COLOR_MAPPING, LEGEND_INTERVAL, LEGEND_START, MAX_COLOR, MID_COLOR,
                      MIN_COLOR, OPACITY, REVERSE_LEGEND, SHOW_LEGEND)
from .heatmap_dialog import CategoryColorsDialog
from .workbench import analyse

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "heatmap_072"
LEGACY = json.loads((FIXTURES / "legacy-072.json").read_text(encoding="utf-8"))
MID = "Color midpoint (blank = automatic)"
OUTSIDE = "Out-of-range color (blank = clamp)"
CUSTOM = {"low": "#112233", "high": "#cc8844", "LOW": "#aa1177", "1": "#88bb22", "01": "#2255bb"}


def oracle():
    import sys
    sys.path.insert(0, str(FIXTURES.parent.parent.parent))
    from tests import heatmap_color_oracle
    return heatmap_color_oracle


def check_heat_map_colors(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, LayoutDialog, capture, drive_dialog,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    ref = oracle()
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "heatmap-colors"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    original_language = i18n.active_language()

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

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

    def reachable(dialog):
        """Run Analysis and every tab lie inside the screen at the current size."""
        dialog.update()
        button = run_button(dialog)
        assert button is not None and button.winfo_viewable()
        assert button.winfo_rooty() + button.winfo_height() <= screen[1], (button.winfo_rooty(), screen)
        assert button.winfo_rootx() + button.winfo_width() <= screen[0]
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
            assert dialog.winfo_rootx() + dialog.winfo_width() <= screen[0]

    def mesh(index):
        figure = app.runs[index].result.figure
        found = next(c for ax in figure.axes for c in ax.collections if isinstance(c, QuadMesh))
        found.update_scalarmappable()      # the colors the next draw would paint
        return found

    def faces(index):
        return mesh(index).get_facecolors()

    def table(index):
        return app.runs[index].result.tables["Heat map data"]

    def find_run(title, number=0):
        return [i for i, run in enumerate(app.runs) if run.title == title][number]

    def edit(index, action):
        app.show("graph", index)
        root.update()
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.edit_analysis(initial_field=app.heat_map_settings_field(app.runs[index]))
        wait()

    # 1. Open the frozen 0.72 project: the three recipes reproduce their frozen colors and carry no new keys.
    path = directory / "legacy-072.alab"
    shutil.copy(FIXTURES / "legacy-072.alab", path)
    app.import_file(path)
    matrix, diverging, categorical = find_run("Numeric", 0), find_run("Numeric", 1), find_run("Categories")
    for index, name in ((matrix, "matrix"), (diverging, "diverging"), (categorical, "categorical")):
        app.open_sheet(("graph", index))
        wait()
        np.testing.assert_allclose(faces(index), LEGACY[name]["rgba"], rtol=1e-12, atol=1e-12)
        assert not {COLOR_MAPPING, OPACITY, CATEGORY_COLORS, SHOW_LEGEND} & set(app.runs[index].options)
    legacy_options = {i: dict(app.runs[i].options) for i in (matrix, diverging, categorical)}
    app.show("graph", matrix)
    root.update()
    shot(root, "window-heatmap-legacy" + suffix + ".png")

    # 2. Double gradient: dynamic fields, an invalid color and a bad legend on their own fields, then a correction.
    def gradient_dialog(dialog):
        controls = dialog.controls
        tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
        # Layout sits next to Graph options while preserving the existing tabs and their relative order.
        assert tabs == ["Variables", "Graph options", "Layout", "Colors", "Categories", "Legend"], tabs
        assert controls[COLOR_MAPPING][1].get() == "Palette" and controls[OPACITY][1].get() == "1.0"
        assert placed(dialog, "Palette") and not placed(dialog, MIN_COLOR) and not placed(dialog, MID_COLOR)
        assert not placed(dialog, LEGEND_START) and not placed(dialog, CATEGORY_COLORS)
        controls[COLOR_MAPPING][1].set("Double gradient")
        dialog.update()
        assert placed(dialog, MIN_COLOR) and placed(dialog, MID_COLOR) and placed(dialog, MAX_COLOR)
        assert placed(dialog, MID) and not placed(dialog, "Palette") and not placed(dialog, "Color scale")
        controls[MIN_COLOR][1].set("#0000ff")
        controls[MID_COLOR][1].set("#ffffff")
        controls[MAX_COLOR][1].set("#ff0000")
        controls[MID][1].set("1")
        controls[MIN_COLOR][1].set("not-a-color")
        rejected(dialog, MIN_COLOR, "valid color", "window-heatmap-color-error.png")
        controls[MIN_COLOR][1].set("#0000ff")
        controls[OPACITY][1].set("1,5")
        rejected(dialog, OPACITY, "between 0 and 1")
        controls[OPACITY][1].set("0,25")
        controls[MID][1].set("9")
        rejected(dialog, MID, "strictly between")
        controls[MID][1].set("1")
        controls[OUTSIDE][1].set("#00aa00")
        dialog.fields.select(2)
        dialog.update()
        shot(dialog, "window-heatmap-colors" + suffix + ".png")
        # Legend: hidden fields follow the checkbox, the start follows the interval.
        controls[SHOW_LEGEND][1].set(False)
        dialog.update()
        assert not placed(dialog, "Color legend orientation") and not placed(dialog, "Color legend title")
        controls[SHOW_LEGEND][1].set(True)
        dialog.update()
        assert placed(dialog, "Color legend orientation") and not placed(dialog, LEGEND_START)
        controls["Color legend orientation"][1].set("Horizontal")
        controls[REVERSE_LEGEND][1].set(True)
        controls["Color legend title"][1].set("$literal$ (a.u.)")
        controls[LEGEND_INTERVAL][1].set("0")
        dialog.update()
        assert placed(dialog, LEGEND_START)
        rejected(dialog, LEGEND_INTERVAL, "greater than zero", "window-heatmap-legend-error.png")
        controls[LEGEND_INTERVAL][1].set("0,001")
        rejected(dialog, LEGEND_INTERVAL, "at most 200")
        controls[LEGEND_INTERVAL][1].set("abc")
        rejected(dialog, LEGEND_INTERVAL, "finite number")
        controls[LEGEND_INTERVAL][1].set("1")
        controls[LEGEND_START][1].set("8")
        rejected(dialog, LEGEND_START, "between the color limits")
        controls[LEGEND_START][1].set("0,5")
        dialog.fields.select(4)
        dialog.update()
        shot(dialog, "window-heatmap-legend" + suffix + ".png")
        reachable(dialog)
        dialog.fields.select(2)

    edit(matrix, gradient_dialog)
    options = app.runs[matrix].options
    assert options[COLOR_MAPPING] == "Double gradient" and options[OPACITY] == 0.25 and options[LEGEND_START] == "0,5"
    assert options["Color legend orientation"] == "Horizontal" and options[REVERSE_LEGEND] is True
    assert "Palette" not in options and "Color scale" not in options, options
    expected = [ref.color(v, low=0., high=4., minimum="#0000ff", maximum="#ff0000", opacity=.25, midpoint=1.,
                          middle="#ffffff", missing="#445566", outside="#00aa00")
                for v in table(matrix).to_numpy().flat]
    np.testing.assert_allclose(faces(matrix), expected, rtol=0, atol=2 / 255)
    np.testing.assert_allclose(faces(matrix)[:, 3], np.array(expected)[:, 3], atol=1e-12)
    bar = mesh(matrix).colorbar
    assert bar.orientation == "horizontal" and bar.ax.xaxis_inverted() and bar.ax.get_xlabel() == "$literal$ (a.u.)"
    np.testing.assert_allclose(bar.get_ticks(), ref.ticks(0, 4, 1, .5), atol=1e-12)
    pd.testing.assert_frame_equal(table(matrix), pd.DataFrame(
        np.asarray(LEGACY["matrix"]["data"], float), index=LEGACY["matrix"]["index"], columns=LEGACY["matrix"]["columns"]
    ).rename_axis("Row"))
    app.show("graph", matrix)
    root.update()
    shot(root, "window-heatmap-double-gradient" + suffix + ".png")
    gradient_recipe = dict(options)

    # 3. A cancelled dialog changes neither the recipe nor the result.
    before = app.runs[matrix].result
    app.show("graph", matrix)

    def cancelled(dialog):
        dialog.controls[COLOR_MAPPING][1].set("Single gradient")
        dialog.controls[OPACITY][1].set("0.9")
        dialog.cancel()
        dialog.ok = lambda *args: None

    tools.drive_dialog(tools.AnalysisDialog, cancelled)
    app.edit_analysis(initial_field=app.heat_map_settings_field(app.runs[matrix]))
    wait()
    assert app.runs[matrix].result is before and app.runs[matrix].options == gradient_recipe

    # 4. Categories: the table editor (Cancel, a bad color, Apply), one color per level text.
    def category_dialog(dialog):
        controls = dialog.controls
        assert placed(dialog, CATEGORY_COLORS) and not placed(dialog, COLOR_MAPPING)
        assert not placed(dialog, "Color legend orientation") and not placed(dialog, LEGEND_INTERVAL)
        field = dialog.field_rows[CATEGORY_COLORS][1]
        assert field.summary.cget("text") == "0 of 5 categories have a chosen color.", field.summary.cget("text")
        shot_state = {}

        def editor_cancel(editor):
            assert [row[0] for row in editor.rows] == ["low", "high", "LOW", "1", "01"], editor.rows
            editor.rows[0][1].set("#ff0000")
            editor.cancel()
            editor.ok = lambda *args: None

        tools.drive_dialog(CategoryColorsDialog, editor_cancel)
        field.edit()
        assert field.values() == {}, field.values()

        def editor_apply(editor):
            for (level, text, _), color in zip(editor.rows, CUSTOM.values(), strict=True):
                assert level in CUSTOM
                text.set(CUSTOM[level])
            editor.rows[1][1].set("no such color")
            with patch.object(tools.messagebox, "showerror"):
                assert editor.validate() is False
            assert editor.message.cget("text") and editor.winfo_exists()
            shot(editor, "window-heatmap-category-error" + suffix + ".png")
            editor.rows[1][1].set(CUSTOM["high"])
            shot(editor, "window-heatmap-categories" + suffix + ".png")

        tools.drive_dialog(CategoryColorsDialog, editor_apply)
        field.edit()
        assert field.values() == CUSTOM, field.values()
        assert field.summary.cget("text") == "5 of 5 categories have a chosen color."
        controls[REVERSE_LEGEND][1].set(True)
        controls["Color legend title"][1].set("$class$ · level")
        controls[OPACITY][1].set("0.8")
        dialog.fields.select(3)
        dialog.update()
        shot(dialog, "window-heatmap-category-dialog" + suffix + ".png")
        reachable(dialog)
        dialog.fields.select(3)

    edit(categorical, category_dialog)
    options = app.runs[categorical].options
    assert options[CATEGORY_COLORS] == CUSTOM and options[REVERSE_LEGEND] is True and options[OPACITY] == 0.8
    assert COLOR_MAPPING not in options and "Color legend orientation" not in options, options
    expected = [(*ref.rgba(CUSTOM.get(v, "#445566"))[:3], 1.0 if v is None else .8)
                for v in ["low", "high", "LOW", "1", "01", None]]
    np.testing.assert_allclose(faces(categorical), expected, atol=1e-12)
    legend = app.runs[categorical].result.figure.axes[0].get_legend()
    assert [t.get_text() for t in legend.get_texts()] == list(CUSTOM)[::-1]
    assert legend.get_title().get_text() == "$class$ · level" and not legend.get_title().get_parse_math()
    app.show("graph", categorical)
    root.update()
    shot(root, "window-heatmap-categories-graph" + suffix + ".png")
    category_recipe = dict(options)

    # 5. Transpose and reverse through the dialog, then edit and exclude cells: colors follow the level text.
    def transpose(dialog):
        dialog.controls["Transpose"][1].set(True)
        dialog.controls["Reverse rows"][1].set(True)

    edit(categorical, transpose)
    shown = table(categorical)
    colors = faces(categorical).reshape(*shown.shape, 4)
    for (row, col), value in np.ndenumerate(shown.to_numpy()):
        if isinstance(value, str):
            np.testing.assert_allclose(colors[row, col, :3], ref.rgba(CUSTOM[value])[:3], atol=1e-12)
    assert app.runs[categorical].options[CATEGORY_COLORS] == CUSTOM
    app.show("data", "Categories")
    app.edit_cell(1, 2, "LOW")          # the only "high" becomes LOW: the level disappears
    wait()
    names = [t.get_text() for t in app.runs[categorical].result.figure.axes[0].get_legend().get_texts()]
    assert "high" not in names and app.runs[categorical].options[CATEGORY_COLORS] == CUSTOM, names
    app.show("data", "Categories")
    app.edit_cell(1, 2, "high")         # and it returns with its own color
    wait()
    shown = table(categorical)
    colors = faces(categorical).reshape(*shown.shape, 4)
    seen = {value for value in shown.to_numpy().flat if isinstance(value, str)}
    assert seen == set(CUSTOM), seen
    for (row, col), value in np.ndenumerate(shown.to_numpy()):
        if isinstance(value, str):
            np.testing.assert_allclose(colors[row, col, :3], ref.rgba(CUSTOM[value])[:3], atol=1e-12)
    app.show("data", "Categories")
    app.current_grid.select((2, 2))
    app.toggle_exclusion()
    wait()
    excluded = table(categorical)
    assert sum(isinstance(v, str) for v in excluded.to_numpy().flat) == 4, excluded
    app.show("data", "Categories")
    app.current_grid.select((2, 2))
    app.toggle_exclusion()
    wait()
    restored = table(categorical)
    assert sum(isinstance(v, str) for v in restored.to_numpy().flat) == 5, restored

    # 6. Italian: translated captions, choices, notes and errors; the recipe keeps its canonical values.
    def italian(dialog):
        controls = dialog.controls
        # Layout occupies tab index 2; Colori, Categorie, Legenda follow at 3..5.
        assert [dialog.fields.tab(i, "text") for i in range(3, 6)] == ["Colori", "Categorie", "Legenda"]
        captions = {name: dialog.field_rows[name][0].cget("text")
                    for name in (COLOR_MAPPING, MIN_COLOR, MID_COLOR, MAX_COLOR, OPACITY, SHOW_LEGEND,
                                 "Color legend orientation", REVERSE_LEGEND, "Color legend title", LEGEND_INTERVAL,
                                 LEGEND_START, CATEGORY_COLORS)}
        assert captions[COLOR_MAPPING] == "Mappatura dei colori" and captions[OPACITY] == "Opacità dei colori"
        assert captions[LEGEND_INTERVAL] == "Intervallo dei tick della legenda", captions
        mapping = dialog.field_rows[COLOR_MAPPING][1]
        assert list(mapping.cget("values")) == ["Tavolozza", "Gradiente singolo", "Gradiente doppio"]
        assert controls[COLOR_MAPPING][1].get() == "Palette"
        mapping.set("Gradiente doppio")
        mapping.event_generate("<<ComboboxSelected>>")
        dialog.update()
        assert controls[COLOR_MAPPING][1].get() == "Double gradient" and placed(dialog, MID_COLOR)
        orientation = dialog.field_rows["Color legend orientation"][1]
        assert list(orientation.cget("values")) == ["Verticale", "Orizzontale"]
        controls[OPACITY][1].set("2")
        message = rejected(dialog, OPACITY, "compreso tra 0 e 1", "window-heatmap-it-error.png",
                           caption="Opacità dei colori")
        assert "must be" not in message
        controls[OPACITY][1].set("1")
        controls[MIN_COLOR][1].set("rosso scuro")
        rejected(dialog, MIN_COLOR, "colore", caption="Colore del minimo")
        controls[MIN_COLOR][1].set("#222266")
        controls[LEGEND_INTERVAL][1].set("0")
        rejected(dialog, LEGEND_INTERVAL, "maggiore di zero", caption="Intervallo dei tick della legenda")
        controls[LEGEND_INTERVAL][1].set("")
        dialog.fields.select(3)
        dialog.update()
        shot(dialog, "window-heatmap-it-colors" + suffix + ".png")
        dialog.fields.select(5)
        dialog.update()
        shot(dialog, "window-heatmap-it" + suffix + ".png")
        reachable(dialog)

    try:
        i18n.set_language("it")
        edit(diverging, italian)
        italian_recipe = dict(app.runs[diverging].options)
        app.show("graph", diverging)
        root.update()
        shot(root, "window-heatmap-it-graph" + suffix + ".png")
        i18n.set_language("en")

        def english(dialog):
            assert dialog.field_rows[COLOR_MAPPING][1].get() == "Double gradient"
            assert dialog.field_rows[OPACITY][0].cget("text") == "Color opacity"

        edit(diverging, english)
        assert app.runs[diverging].options == italian_recipe, (app.runs[diverging].options, italian_recipe)
        assert italian_recipe[COLOR_MAPPING] == "Double gradient" and italian_recipe[MIN_COLOR] == "#222266"
        assert "Color legend title" not in italian_recipe or italian_recipe["Color legend title"] == ""
    finally:
        i18n.set_language(original_language)

    # 7. Inspector and Graph settings: no line controls, a way to the editor, drafts, and the general style stays.
    app.show("graph", matrix)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and not panel.elements and "colors" in panel.widgets
    assert not any(widget.winfo_ismapped() for field in panel.fields.values() for widget in field["shown"])
    panel.vars["title"].set("Expression after treatment")
    panel.vars["legend"].set("Default")
    panel._now("title")
    root.update()
    assert app.runs[matrix].result.figure.axes[0].get_title() == "Expression after treatment"
    assert "Expression" not in str(app.runs[matrix].style or {}), "a draft is not confirmed"
    panel.cancel()
    root.update()
    assert app.runs[matrix].result.figure.axes[0].get_title() == "Heat map"
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    panel.vars["title"].set("Expression after treatment")
    panel._now("title")
    assert panel.apply()
    assert app.runs[matrix].style["title"] == "Expression after treatment"
    shot(root, "window-heatmap-inspector" + suffix + ".png")
    # The Inspector shortcut opens the same editor on its colors; the confirmed title survives the new gradient.

    def single(dialog):
        assert dialog.fields.select() == str(dialog.field_rows[COLOR_MAPPING][1].master)
        assert dialog.focus_get() is dialog.field_rows[COLOR_MAPPING][1], dialog.focus_get()
        dialog.controls[COLOR_MAPPING][1].set("Single gradient")
        dialog.controls[MIN_COLOR][1].set("#003300")
        dialog.controls[MAX_COLOR][1].set("#ffee00")
        dialog.controls["Color legend orientation"][1].set("Vertical")

    tools.drive_dialog(tools.AnalysisDialog, single)
    panel.widgets["colors"].invoke()
    wait()
    root.update()
    run = app.runs[matrix]
    assert run.options[COLOR_MAPPING] == "Single gradient" and run.style["title"] == "Expression after treatment"
    assert run.result.figure.axes[0].get_title() == "Expression after treatment"
    assert MID_COLOR not in run.options
    expected = [ref.color(v, low=0., high=4., minimum="#003300", maximum="#ffee00", opacity=.25, outside="#00aa00")
                for v in table(matrix).to_numpy().flat]
    np.testing.assert_allclose(faces(matrix), expected, rtol=0, atol=2 / 255)
    assert mesh(matrix).colorbar.orientation == "vertical"
    app.show("graph", matrix)
    root.update()
    shot(root, "window-heatmap-single-gradient" + suffix + ".png")

    # 8. Hidden legend leaves no axis; legend options never touch the table.
    def hidden(dialog):
        dialog.controls[SHOW_LEGEND][1].set(False)

    keep = table(matrix).copy()
    edit(matrix, hidden)
    assert len(app.runs[matrix].result.figure.axes) == 1 and mesh(matrix).colorbar is None
    pd.testing.assert_frame_equal(table(matrix), keep)

    def shown_again(dialog):
        dialog.controls[SHOW_LEGEND][1].set(True)

    edit(matrix, shown_again)
    assert mesh(matrix).colorbar is not None

    # 9. Export: CSV, PNG, SVG, PDF; a two-panel layout; Use Result as Data on the numeric sheet.
    app.show("result", matrix)
    app.result_tabs.select(0)
    target = out / "heat-map.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
    np.testing.assert_allclose(exported.to_numpy(), table(matrix).to_numpy(), equal_nan=True)
    app.show("graph", matrix)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"heat-map.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension
    svg = (out / "heat-map.svg").read_text(encoding="utf-8")
    assert "<svg" in svg and "image" in svg or "path" in svg

    def compose(dialog):
        dialog.name.set("Heat maps")
        dialog.columns.set("2")
        dialog.list.selection_clear(0, "end")
        for number, item in enumerate(dialog.runs):
            if app.runs.index(item) in {matrix, categorical}:
                dialog.list.selection_set(number)
        dialog.add_selected()

    tools.drive_dialog(tools.LayoutDialog, compose)
    app.new_layout()
    root.update()
    layout = next(i for i, item in enumerate(app.layouts) if item.name == "Heat maps")
    app.show("layout", layout)
    root.update()
    shot(root, "window-heatmap-layout" + suffix + ".png")
    for extension in ("svg", "pdf"):
        target = out / f"heat-maps-layout.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, extension
    ET.parse(out / "heat-maps-layout.svg")
    before = set(app.tables)
    app.show("result", matrix)
    app.result_tabs.select(0)
    app.use_result_as_data()
    created = set(app.tables) - before
    assert len(created) == 1
    np.testing.assert_allclose(app.tables[next(iter(created))].raw.iloc[:, 1:].to_numpy(dtype=float),
                               table(matrix).to_numpy(), equal_nan=True)
    wait()

    # 10. Save, reopen the graph before the worksheet: same recipes, tables and colors.
    saved = {i: (dict(app.runs[i].options), table(i).copy(), faces(i).copy()) for i in (matrix, categorical)}
    app.path = directory / "heatmap-colors-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for title in ("Numeric", "Categories"):
        for number, run in enumerate(app.runs):
            if run.title == title:
                app.open_sheet(("graph", number))
                wait()
    matrix_again, categorical_again = find_run("Numeric", 0), find_run("Categories")
    for old, new in ((matrix, matrix_again), (categorical, categorical_again)):
        assert app.runs[new].options == saved[old][0], (app.runs[new].options, saved[old][0])
        pd.testing.assert_frame_equal(table(new), saved[old][1])
        np.testing.assert_allclose(faces(new), saved[old][2], atol=1e-12)
    assert app.runs[categorical_again].options[CATEGORY_COLORS] == CUSTOM
    assert app.runs[matrix_again].style["title"] == "Expression after treatment"
    assert app.runs[find_run("Numeric", 1)].options.get(COLOR_MAPPING) == "Double gradient"
    app.show("graph", categorical_again)
    root.update()
    # Leave the shared app as the next check expects it: no Inspector wanted or open.
    if app.inspector is not None:
        app.toggle_inspector()
    app.inspector_wanted = False
    root.update()
    assert app.inspector is None and not errors, errors
