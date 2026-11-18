"""Desktop smoke check for Grouped distribution plot (box and violin cells by category and series).

``tramastat.py --smoke`` calls :func:`check_grouped_distributions` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=grouped-distributions python tramastat.py --smoke DIR``.
With ``TRAMASTAT_SMOKE_SCREENSHOTS=1`` the dialog, graph and Inspector captures go to ``DIR/grouped-distributions``.

Synthetic data only: the packaged fixture (tests/data/grouped_distributions). Expected values are the frozen
numbers of the independent oracle, not computed by the module under test.
"""
import json
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .distribution_graphs import BOX_VIOLIN
from .figure_export_dialog import FigureExportDialog
from .grid_data import paste_block
from .grouped_distributions import (CELLS_SHEET, DENSITY_SHEET, GROUPED_DISTRIBUTIONS, OBSERVATIONS_SHEET,
                                    cell_identity)
from .presentation import graph_groups

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "grouped_distributions"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
LEGACY = json.loads((FIXTURES / "legacy.json").read_text(encoding="utf-8"))
TITLE, WIDE = "Signal by visit", "Signal by column"
PLACEBO = "box:" + cell_identity("str:Week $2$", "str:Placebo")
VIOLIN_PLACEBO = "violin:" + cell_identity("str:Week $2$", "str:Placebo")
VIOLIN_DRUG = "violin:" + cell_identity("str:Week $2$", "str:Drug")
PURPLE = list(__import__("matplotlib.colors", fromlist=["to_rgb"]).to_rgb("#9b4174"))
RECIPE = {"Response": "Signal", "Category": "Visit", "Split by": "Treatment", "Style": "Box"}


def worksheet():
    return pd.read_csv(FIXTURES / "observations.csv")


def check_grouped_distributions(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, LayoutDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    previous_language = i18n.active_language()
    # The main flow runs in the language of the preferences; one dialog follows in the other language.
    start = previous_language if previous_language in ("en", "it") else "en"
    other = "it" if start == "en" else "en"
    i18n.set_language(start)
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "grouped-distributions"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    frame = worksheet()
    path = directory / "grouped-distributions.alab"
    wide = pd.DataFrame({"Control": [4.1, 4.8, 5.0, 5.2, 5.9, 6.1, 7.0, 14.0],
                         "Drug": [5.5, 6.0, 6.2, 6.8, 7.0, 7.5, 7.9, 9.0]})
    save_project(path, {TITLE: Dataset(frame.copy()), WIDE: Dataset(wide.copy())})
    app.import_file(path)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, english="", shot_name=None):
        """The dialog stays open on ``field``; ``english`` is the engine message, shown in the active language."""
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        wanted = i18n.translate_message(english, "grouped.error.", {"field": i18n.ui})
        assert i18n.ui(field) in message and wanted in message, (message, wanted)
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            shot(dialog, shot_name)
        return message

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
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
        dialog.fields.select(0)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def commit(widget, variable, value):
        variable.set(value)
        widget.focus_force()
        root.update()
        widget.event_generate("<Return>")
        root.update()

    def click(x, y):
        from matplotlib.backend_bases import MouseEvent

        canvas = app.graph_canvas
        pixel = canvas.figure.axes[0].transData.transform((x, y))
        canvas.callbacks.process("button_press_event", MouseEvent("button_press_event", canvas, *pixel, button=1))
        root.update()

    def edge(group):
        return np.atleast_2d(group.artists[0][0].get_edgecolor())[0][:3].tolist()

    def legend_text(index):
        legend = app.runs[index].result.figure.axes[0].get_legend()
        return None if legend is None else [text.get_text() for text in legend.get_texts()]

    # 1. The dialog: fields, hidden fields, two equal roles forwarded and corrected in the same dialog.
    def first_dialog(dialog):
        tools.pick_method(dialog, GROUPED_DISTRIBUTIONS)
        controls = dialog.controls
        for name in ("Response", "Category", "Split by", "Style", "Whiskers", "Show mean", "Overlay observations"):
            assert placed(dialog, name), name
        for name in ("Bandwidth multiplier", "Median line", "Quartile lines", "Point placement"):
            assert not placed(dialog, name), name
        assert controls["Style"][1].get() == "Box" and controls["Whiskers"][1].get() == "Tukey"
        assert controls["Split by"][1].get() == "" and controls["Overlay observations"][1].get() in (False, 0)
        controls["Response"][1].set("Signal")
        controls["Category"][1].set("Signal")
        rejected(dialog, "Category", "Choose a category column different from the response.",
                 "window-grouped-roles-error" + suffix + ".png")
        controls["Category"][1].set("Visit")
        controls["Split by"][1].set("Visit")
        rejected(dialog, "Split by", "Choose a Split by column different from Response and Category.")
        controls["Split by"][1].set("")
        controls["Response"][1].set("Treatment")
        rejected(dialog, "Response", 'Column "Treatment" contains text or infinite values.')
        controls["Response"][1].set("Signal")
        controls["Split by"][1].set("Treatment")
        # The violin fields replace the box fields; unusable bandwidths keep the dialog open on that field.
        controls["Style"][1].set("Violin")
        dialog.update()
        for name in ("Bandwidth multiplier", "Median line", "Quartile lines"):
            assert placed(dialog, name), name
        assert not placed(dialog, "Whiskers")
        for text in ("0", "-1", "abc", "inf", "nan"):
            controls["Bandwidth multiplier"][1].set(text)
            rejected(dialog, "Bandwidth multiplier", "")
        controls["Bandwidth multiplier"][1].set("1")
        controls["Overlay observations"][1].set(True)
        dialog.update()
        assert placed(dialog, "Point placement")
        controls["Overlay observations"][1].set(False)
        controls["Style"][1].set("Box")
        dialog.update()
        assert placed(dialog, "Whiskers") and not placed(dialog, "Bandwidth multiplier")
        controls["Whiskers"][1].set("Min to max with all observations")
        dialog.update()
        assert placed(dialog, "Point placement") and not placed(dialog, "Overlay observations")
        controls["Whiskers"][1].set("Tukey")
        reachable(dialog)
        shot(dialog, "window-grouped-dialog" + suffix + ".png")

    app.show("data", TITLE)
    tools.drive_dialog(tools.AnalysisDialog, first_dialog)
    app.choose_analysis()
    wait()
    index = len(app.runs) - 1
    run = app.runs[index]
    assert run.method == GROUPED_DISTRIBUTIONS and run.title == TITLE
    assert run.options == {**RECIPE, "Show mean": False, "Overlay observations": False,
                           "Point placement": "Spread exact ties", "Whiskers": "Tukey"} or all(
        run.options[key] == value for key, value in RECIPE.items()), run.options
    assert set(run.options) <= set(RECIPE) | {"Whiskers", "Show mean", "Overlay observations", "Point placement"}

    # 2. The result: values of the independent oracle, the empty slot kept in the sheet and free on the graph.
    cells = table(index, CELLS_SHEET)
    assert cells["N"].tolist() == [5, 4, 4, 0] and cells["Position"].tolist() == [.8, 1.2, 1.8, 2.2]
    for want, got in zip(EXPECTED["cells"], cells.to_dict("records"), strict=True):
        for name, value in want.items():
            if value is None:
                assert pd.isna(got[name]), (name, got)
            elif isinstance(value, str):
                assert got[name] == value
            else:
                assert abs(got[name] - value) < 1e-9, (name, got)
    observations = table(index, OBSERVATIONS_SHEET)
    assert observations["Source row"].tolist() == [item["Source row"] for item in EXPECTED["observations"]]
    assert observations["Value"].tolist() == [item["Value"] for item in EXPECTED["observations"]]
    assert "Position = 1 + j" in table(index, "Settings").to_string()
    app.show("result", index)
    app.result_tabs.select(0)
    shot(root, "window-grouped-cells" + suffix + ".png")
    app.show("graph", index)
    root.update()
    axes = app.runs[index].result.figure.axes[0]
    assert [t.get_text() for t in axes.get_xticklabels()] == EXPECTED["labels"]
    assert all(not t.get_parse_math() for t in axes.get_xticklabels())
    assert legend_text(index) == EXPECTED["legend"]
    assert [group.x for group in graph_groups(axes)] == [.8, 1.2, 1.8]
    shot(root, "window-grouped-box" + suffix + ".png")

    # 3. Change the style in the same analysis dialog; unusable bandwidths stay in it.
    def to_violin(dialog):
        dialog.controls["Style"][1].set("Violin")
        dialog.controls["Overlay observations"][1].set(True)
        dialog.controls["Point placement"][1].set("Jitter")
        dialog.controls["Bandwidth multiplier"][1].set("-2")
        rejected(dialog, "Bandwidth multiplier", "")
        dialog.controls["Bandwidth multiplier"][1].set("inf")
        rejected(dialog, "Bandwidth multiplier", "")
        dialog.controls["Bandwidth multiplier"][1].set("1,5")

    app.show("graph", index)
    tools.drive_dialog(tools.AnalysisDialog, to_violin)
    app.edit_analysis()
    wait()
    run = app.runs[index]
    assert run.options["Style"] == "Violin" and run.options["Bandwidth multiplier"] == 1.5
    assert run.options["Overlay observations"] is True and "Whiskers" not in run.options, run.options
    assert table(index, CELLS_SHEET)["N"].tolist() == [5, 4, 4, 0]
    density = table(index, DENSITY_SHEET)
    assert set(density.columns[:3]) == {"Category", "Series", "Position"}
    assert not density.duplicated(["Category", "Series", "Value"]).any()
    assert len(table(index, OBSERVATIONS_SHEET)) == 13
    app.show("graph", index)
    root.update()
    shot(root, "window-grouped-violin" + suffix + ".png")
    assert legend_text(index) == EXPECTED["legend"]

    # 4. Inspector: a cell is selected, colored and hidden by key; the legend follows the visible cells.
    app.toggle_inspector()
    panel = app.inspector
    axes = app.runs[index].result.figure.axes[0]
    keys = [item["key"] for item in panel.elements]
    assert keys == [f"violin:{cell_identity(c, s)}" for c, s in (
        ("str:Week $2$", "str:Drug"), ("str:Week $2$", "str:Placebo"), ("str:Baseline", "str:Drug"))], keys
    assert [item["name"] for item in panel.elements] == ["Week $2$ · Drug", "Week $2$ · Placebo", "Baseline · Drug"]
    click(1.2, 12)
    assert panel.current["key"] == VIOLIN_PLACEBO, panel.current
    commit(panel.fields["color"]["widget"], panel.vars["element:color"], "#9b4174")
    assert panel.apply()
    assert app.runs[index].style["groups"] == {VIOLIN_PLACEBO: {"color": "#9b4174"}}, app.runs[index].style
    axes = app.runs[index].result.figure.axes[0]
    legend = axes.get_legend()
    assert tuple(np.round(legend.legend_handles[1].get_edgecolor()[:3], 4)) == (0.6078, 0.2549, 0.4549)
    shot(root, "window-grouped-inspector" + suffix + ".png")
    panel.select_group(VIOLIN_DRUG)
    panel.vars["element:visible"].set(False)
    panel._now("element:visible")
    assert [t.get_text() for t in axes.get_legend().get_texts()] == ["Drug", "Placebo"]  # Baseline · Drug is visible
    app.close_inspector()
    app.show("graph", index)

    # 5. Rows in another order (Placebo first), then a cell removed and an observation excluded: the color stays
    #    with its cell, the slots follow the new order of first appearance.
    def rows_of(visit, treatment):
        raw = app.get_dataset().raw
        match = (raw["Visit"].astype(str) == visit) & (raw["Treatment"].astype(str) == treatment)
        return [int(i) for i in np.flatnonzero(match.to_numpy())]

    def reorder():
        dataset = app.get_dataset()
        before = app.worksheet_state(dataset)
        order = sorted(range(len(dataset.raw)), key=lambda i: str(dataset.raw["Treatment"].iloc[i]) != "Placebo")
        block = [["" if pd.isna(value) else str(value) for value in row]
                 for row in dataset.raw.iloc[order].to_numpy()]
        paste_block(dataset, 0, 0, block)
        app.finish_worksheet_edit(dataset, before, "Reorder rows")

    app.show("data", TITLE)
    reorder()
    wait()
    run = app.runs[index]
    assert run.style["groups"][VIOLIN_PLACEBO] == {"color": "#9b4174"}
    cells = table(index, CELLS_SHEET)
    assert [(r.Category, r.Series, r.N, r.Position) for r in cells.itertuples()] == [
        ("Week $2$", "Placebo", 4, .8), ("Week $2$", "Drug", 5, 1.2),
        ("Baseline", "Placebo", 0, 1.8), ("Baseline", "Drug", 4, 2.2)], cells
    assert legend_text(index) == ["Placebo", "Drug"]
    groups = {group.key: group for group in graph_groups(run.result.figure.axes[0])}
    assert groups[VIOLIN_PLACEBO].x == .8 and edge(groups[VIOLIN_PLACEBO]) == PURPLE
    app.show("graph", index)
    root.update()
    app.toggle_inspector()
    app.inspector.select_group(VIOLIN_PLACEBO)
    assert app.inspector.current["key"] == VIOLIN_PLACEBO
    app.close_inspector()
    # Exclude the five observations of Week 2 · Drug one at a time: the cell leaves the graph and the legend.
    drug_rows = rows_of("Week $2$", "Drug")
    assert len(drug_rows) == 5
    for row in drug_rows:
        app.show("data", TITLE)
        app.current_grid.select((row, 2))
        app.toggle_exclusion()
        wait()
    run = app.runs[index]
    now = graph_groups(run.result.figure.axes[0])
    assert [group.key for group in now] == [VIOLIN_PLACEBO, f"violin:{cell_identity('str:Baseline', 'str:Drug')}"]
    assert edge(now[0]) == PURPLE and legend_text(index) == ["Placebo", "Drug"]
    placebo_rows = rows_of("Week $2$", "Placebo")
    app.show("data", TITLE)
    app.current_grid.select((placebo_rows[0], 2))
    app.toggle_exclusion()
    wait()
    after = table(index, CELLS_SHEET).set_index(["Category", "Series"])
    assert after.loc[("Week $2$", "Placebo"), "N"] == 3 and after.loc[("Week $2$", "Drug"), "N"] == 0
    assert app.runs[index].style["groups"][VIOLIN_PLACEBO] == {"color": "#9b4174"}
    app.show("graph", index)
    root.update()
    app.toggle_inspector()
    app.inspector.select_group(VIOLIN_PLACEBO)
    assert app.inspector.current["key"] == VIOLIN_PLACEBO
    app.close_inspector()
    for row in [*drug_rows, placebo_rows[0]]:
        app.show("data", TITLE)
        app.current_grid.select((row, 2))
        app.toggle_exclusion()
        wait()
    assert table(index, CELLS_SHEET)["N"].tolist() == [4, 5, 0, 4]

    # 6. The other language: translated captions, canonical recipe, sheets that keep their English names.
    i18n.set_language(other)
    words = {"en": {"Category", "Split by", "Response"}, "it": {"Categoria", "Dividi per", "Risposta"}}[other]
    try:
        def other_language(dialog):
            tools.pick_method(dialog, GROUPED_DISTRIBUTIONS)
            labels = {widget.cget("text") for widget in _descendants(dialog) if "text" in widget.keys()}
            assert words <= labels, sorted(labels)
            controls = dialog.controls
            controls["Response"][1].set("Signal")
            controls["Category"][1].set("Visit")
            controls["Split by"][1].set("Treatment")
            assert dialog.field_rows["Style"][1].get() == i18n.ui("Box")
            reachable(dialog)
            shot(dialog, f"window-grouped-dialog-{other}" + suffix + ".png")

        app.show("data", TITLE)
        tools.drive_dialog(tools.AnalysisDialog, other_language)
        app.choose_analysis()
        wait()
        other_index = len(app.runs) - 1
        assert app.runs[other_index].options["Style"] == "Box" and app.runs[other_index].options["Split by"] == "Treatment"
        app.show("graph", other_index)
        root.update()
        shot(root, f"window-grouped-box-{other}" + suffix + ".png")
    finally:
        i18n.set_language(start)
    assert table(other_index, CELLS_SHEET)["N"].tolist() == [4, 5, 0, 4]

    # 7. Two graphs side by side in a layout, saved, reopened and exported as vectors; the published
    #    Box / violin recipe still gives the same sheets in both input modes.
    def legacy_dialog(dialog):
        tools.pick_method(dialog, BOX_VIOLIN)
        dialog.controls["Response"][1].set("Signal")
        dialog.controls["Group"][1].set("Visit")

    app.show("data", TITLE)
    tools.drive_dialog(tools.AnalysisDialog, legacy_dialog)
    app.choose_analysis()
    wait()
    legacy_index = len(app.runs) - 1
    assert app.runs[legacy_index].method == BOX_VIOLIN
    summary = table(legacy_index, "Group summary")
    assert summary["Group"].tolist() == ["Week $2$", "Baseline"]

    def wide_dialog(dialog):
        tools.pick_method(dialog, BOX_VIOLIN)
        dialog.controls["Input"][1].set("Separate columns")
        tools.select_columns(dialog, "Variables", {"Control", "Drug"})

    app.show("data", WIDE)
    tools.drive_dialog(tools.AnalysisDialog, wide_dialog)
    app.choose_analysis()
    wait()
    wide_index = len(app.runs) - 1
    assert table(wide_index, "Group summary")["Group"].tolist() == ["Control", "Drug"]
    assert table(wide_index, "Group summary")["N"].tolist() == [8, 8]

    def compose(name, panels):
        def choose(dialog):
            dialog.name.set(name)
            dialog.columns.set("2")
            dialog.list.selection_clear(0, "end")
            for position, item in enumerate(dialog.runs):
                if app.runs.index(item) in panels:
                    dialog.list.selection_set(position)
            dialog.add_selected()
        tools.drive_dialog(tools.LayoutDialog, choose)
        app.new_layout()
        root.update()
        return len(app.layouts) - 1

    layout_title = "Grouped and published box plots"
    layout = compose(layout_title, {index, wide_index})
    assert app.layouts[layout].columns == 2 and len(app.layouts[layout].panels) == 2
    app.path = directory / "grouped-distributions-layout.alab"
    assert app.save()
    app.import_file(app.path)
    root.update()
    layout = next(i for i, item in enumerate(app.layouts) if item.name == layout_title)
    reopened = [i for i, item in enumerate(app.runs) if item.method == GROUPED_DISTRIBUTIONS]
    assert reopened and app.runs[reopened[0]].options["Style"] == "Violin"
    app.show("layout", layout)
    app.recalculate_layout(layout)
    wait()
    app.show("layout", layout)
    root.update()
    shot(root, "window-grouped-layout" + suffix + ".png")
    # The reopened project restores the color the Inspector applied before the rows were excluded.
    app.open_sheet(("graph", reopened[0]))
    wait()
    assert app.runs[reopened[0]].style["groups"][VIOLIN_PLACEBO] == {"color": "#9b4174"}

    def export(target, configure):
        def act(dialog):
            configure(dialog)
            dialog.update()
        tools.drive_dialog(FigureExportDialog, act)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)), \
                patch.object(app, "error") as error:
            app.export_with_options()
        assert not error.called, error.call_args
        assert target.exists(), target

    def vector(fmt):
        def configure(dialog):
            dialog.format.set(fmt)
            dialog.width.set("160")
            if fmt == "SVG":
                dialog.svg_text.set("Text")
        return configure

    from .layout_svg_smoke import SVG, inspect, texts
    from .pdf_bundle_smoke import read_pdf

    app.show("layout", layout)
    svg_path = out / "grouped-layout.svg"
    export(svg_path, vector("SVG"))
    document, ids, refs = inspect(svg_path, 160, 160 * 3.6 / 8.4)
    words = " ".join(texts(document))
    assert "Week $2$" in words and "Baseline" in words and "Placebo" in words, words
    assert not document.findall(".//" + SVG + "image") and document.findall(".//" + SVG + "path")
    pdf_path = out / "grouped-layout.pdf"
    export(pdf_path, vector("PDF"))
    [(size, text, images)] = read_pdf(pdf_path)
    assert images == 0 and "Week" in text and "Placebo" in text, (images, text)

    # 8. Sheets as data and as CSV.
    app.show("result", index)
    app.result_tabs.select(0)
    app.use_result_as_data()
    used = app.tables[next(name for name in app.tables if name.startswith(CELLS_SHEET))].raw
    assert used["N"].tolist() == [4, 5, 0, 4] and used["Category"].tolist()[0] == "Week $2$"
    app.show("result", index)
    app.result_tabs.select(1)
    csv_path = out / "grouped-observations.csv"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    exported = pd.read_csv(csv_path, index_col=0)   # the app writes the result index, as for every result sheet
    assert list(exported.columns[:5]) == ["Source row", "Category", "Series", "Value", "Position"], exported.columns
    assert len(exported) == 13 and exported["Source row"].tolist() == sorted(exported["Source row"].tolist())
    assert set(exported["Series"]) == {"Drug", "Placebo"} and set(exported["Category"]) == {"Week $2$", "Baseline"}
    figure = app.runs[index].result.figure
    figure.savefig(out / "grouped.png", dpi=100)
    figure.savefig(out / "grouped.svg")
    figure.savefig(out / "grouped.pdf")
    assert b"<svg " in (out / "grouped.svg").read_bytes() and (out / "grouped.pdf").read_bytes()[:4] == b"%PDF"
    assert (out / "grouped.png").stat().st_size > 1000
    app.path = out / "grouped-distributions.alab"
    assert app.save()
    assert not errors, errors
    i18n.set_language(previous_language)


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)
