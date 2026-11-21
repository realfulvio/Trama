"""Desktop smoke check for Power and sample size from expected means and SDs (Tools → Power and sample size…).

``tramastat.py --smoke`` calls :func:`check_power_plan` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=power-from-summary python tramastat.py --smoke DIR``.

Synthetic inputs only. Expected values are the frozen numbers of the independent oracle of the packet
(tests/data/power_from_summary/expected.json, computed from distribution tails and a minimum scan), not computed
by the module under test.
"""
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from . import power_plan as pp
from .graph_dialog import GraphFormatDialog
from .presentation import Layout

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "power_from_summary"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
HOST = "Power analysis"


def check_power_plan(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox and filedialog."""
    wait = tools.wait_for_calculation
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "power-from-summary"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as report:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = report.call_args.args[1]
        assert (caption or field) in message and contains in message, message
        # The tab that holds the field is selected and the keyboard focus is on it.
        assert dialog.fields.select() == str(dialog.field_rows[field][1].master), field
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

    def setv(dialog, name, value):
        dialog.controls[name][1].set(value)
        dialog.update()

    def summary(index):
        return app.runs[index].result.tables[pp.METHOD]["Value"].to_dict()

    def check_oracle(index, name):
        got, want = summary(index), EXPECTED[name]
        for key, value in want.items():
            assert key in got, (name, key, got)
            if isinstance(value, str):
                assert got[key] == value, (name, key, got[key], value)
            else:
                np.testing.assert_allclose(float(got[key]), value, rtol=2e-8, atol=5e-11, err_msg=f"{name}/{key}")

    original_language = i18n.active_language()
    i18n.set_language("en")
    # The check gives back the project tabs it opens: the application allows six and later checks open their own.
    home_tab, tabs_before = app.active_project, set(app.projects)
    app.dirty = False
    app.new_project()
    assert app.active_data is None and not app.tables

    # 1. Tools in a project without tables: errors stay in the dialog on the right page, hidden inputs never block.
    def allocation_case(dialog):
        assert dialog.method == pp.METHOD
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Design", "Effect", "Curve"]
        assert dialog.controls[pp.GOAL][1].get() == "Sample size"
        assert dialog.controls[pp.DESIGN][1].get() == "One-sample t"
        assert dialog.controls[pp.EFFECT_INPUT][1].get() == pp.STANDARDIZED_EFFECT
        assert not placed(dialog, pp.ALLOCATION) and not placed(dialog, pp.GROUPS)
        setv(dialog, pp.DESIGN, "Independent t")
        assert placed(dialog, pp.TARGET) and not placed(dialog, pp.SIZE) and placed(dialog, pp.ALLOCATION)
        assert not placed(dialog, pp.GROUPS) and placed(dialog, pp.STANDARDIZED_EFFECT)
        assert not placed(dialog, pp.MEAN_A) and not placed(dialog, pp.GROUP_MEANS)
        shot(dialog, "window-power-design" + suffix + ".png")
        setv(dialog, pp.EFFECT_INPUT, pp.MEANS)
        assert placed(dialog, pp.MEAN_A) and placed(dialog, pp.MEAN_B) and placed(dialog, pp.COMMON_SD)
        assert not placed(dialog, pp.STANDARDIZED_EFFECT) and not placed(dialog, pp.NULL_MEAN)
        # A hidden field with junk never blocks the calculation.
        dialog.controls[pp.STANDARDIZED_EFFECT][1].set("not a number")
        dialog.controls[pp.GROUP_MEANS][1].set("1; ;2")
        dialog.controls[pp.MEAN_A][1].set("5")
        dialog.controls[pp.MEAN_B][1].set("5")
        dialog.controls[pp.COMMON_SD][1].set("4")
        rejected(dialog, pp.MEAN_A, "zero", "window-power-error-equal-means.png")
        dialog.controls[pp.MEAN_B][1].set("7")
        dialog.controls[pp.ALLOCATION][1].set("2:3:4")
        rejected(dialog, pp.ALLOCATION, "two whole numbers", "window-power-error-allocation.png")
        dialog.controls[pp.ALLOCATION][1].set("0:1")
        rejected(dialog, pp.ALLOCATION, "two whole numbers")
        dialog.controls[pp.ALLOCATION][1].set("2:3")
        dialog.controls[pp.GOAL][1].set("Power")
        dialog.update()
        assert placed(dialog, pp.SIZE) and not placed(dialog, pp.TARGET)
        dialog.controls[pp.SIZE][1].set("51")
        message = rejected(dialog, pp.SIZE, "multiple of 2", "window-power-error-n.png", caption="N (per group")
        assert "50 or 52" in message, message
        dialog.controls[pp.GOAL][1].set("Sample size")
        dialog.update()
        dialog.controls[pp.TARGET][1].set("0.8")
        setv(dialog, pp.SHOW_CURVE, True)
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-power-effect" + suffix + ".png")
        dialog.fields.select(2)
        dialog.update()
        shot(dialog, "window-power-curve-options" + suffix + ".png")
        dialog.fields.select(0)
        dialog.update()

    tools.drive_dialog(tools.AnalysisDialog, allocation_case)
    app.power_planning()
    wait()
    assert app.active_data == HOST, app.active_data
    first = len(app.runs) - 1
    run = app.runs[first]
    assert run.method == pp.METHOD and run.title == HOST
    assert run.options == {
        "Goal": "Sample size", "Design": "Independent t", "Effect input": "Means and SD", "Alpha": 0.05,
        "Target power": 0.8, "Allocation A:B": "2:3", "Mean A": 5.0, "Mean B": 7.0, "Common SD": 4.0,
        "Show power curve": True}, run.options
    check_oracle(first, "allocation")
    sheet = run.result.tables[pp.METHOD]["Value"]
    assert sheet["N A"] == 54 and sheet["N B"] == 81 and sheet["Allocation A:B"] == "2:3"
    curve = run.result.tables[pp.CURVE_SHEET]
    assert list(curve.columns) == ["N", "Total N", "Power", "N A", "N B"] and 2 <= len(curve) <= 200
    assert curve["N"].is_monotonic_increasing and curve["N"].is_unique
    assert 54 in curve["N"].tolist() and 52 in curve["N"].tolist()
    (directory / "power-curve-points.txt").write_text(f"{len(curve)} points\n", encoding="utf-8")
    figure = run.result.figure
    assert figure is not None and any(list(line.get_xdata()) == curve["Total N"].tolist()
                                      for line in figure.axes[0].lines)
    assert figure.axes[0].get_ylim() == (0.0, 1.0)
    # The graph is a native result: listed under Graphs, drawn, exported, with an Inspector.
    graphs = dict((title, entries) for title, entries, *_ in app.sheet_sections())["Graphs"]
    assert any(item[0] == run.name and item[1] == ("graph", first) for item in graphs), graphs
    app.show("graph", first)
    root.update()
    shot(root, "window-power-graph" + suffix + ".png")
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn series"
    panel.select_group(panel.elements[0]["key"])
    panel.vars["element:color"].set("#9b4174")
    widget = panel.fields["color"]["widget"]
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert "#9b4174" in str(app.runs[first].style), app.runs[first].style
    app.toggle_inspector()
    root.update()
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Power for A:B = 2:3"))
    app.format_graph()
    wait()
    assert app.runs[first].result.figure.axes[0].get_title() == "Power for A:B = 2:3"
    app.show("graph", first)
    root.update()
    shot(root, "window-power-graph-formatted" + suffix + ".png")

    # 2. Results: the sheet, the curve sheet, CSV and figure exports.
    app.show("result", first)
    root.update()
    shot(root, "window-power-result" + suffix + ".png")
    for position, name in enumerate((pp.METHOD, pp.CURVE_SHEET)):
        app.result_tabs.select(position)
        target = out / f"power-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 5, name
    exported = pd.read_csv(out / "power-1.csv", index_col=0, encoding="utf-8-sig")
    assert list(exported.columns) == ["N", "Total N", "Power", "N A", "N B"]
    app.show("graph", first)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"power-curve.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.read_bytes().startswith(magic) or magic in target.read_bytes()[:400], extension

    # 3. Use Result as Data resumes the power sheet as an editable table.
    app.show("result", first)
    app.result_tabs.select(0)
    before = set(app.tables)
    app.use_result_as_data()
    copied_title = next(iter(set(app.tables) - before))
    copied = app.tables[copied_title].frame()
    assert "Value" in copied.columns and "N A" in copied.iloc[:, 0].tolist(), copied
    app.show("result", first)
    app.result_tabs.select(1)
    app.use_result_as_data()
    pasted = [title for title in app.tables if title.startswith(pp.CURVE_SHEET)]
    assert pasted and list(app.tables[pasted[-1]].frame().columns) == ["N", "Total N", "Power", "N A", "N B"]

    # 4. A second design in the same project: one-way ANOVA from group means, a curve for the alternative graph.
    def anova_case(dialog):
        setv(dialog, pp.DESIGN, "One-way ANOVA")
        setv(dialog, pp.EFFECT_INPUT, pp.MEANS)
        assert not placed(dialog, pp.ALLOCATION) and placed(dialog, pp.GROUP_MEANS) and placed(dialog, pp.COMMON_SD)
        assert not placed(dialog, pp.GROUPS)
        dialog.controls[pp.GROUP_MEANS][1].set("12; ;15")
        rejected(dialog, pp.GROUP_MEANS, "item 2 is empty", "window-power-error-means-list.png")
        dialog.controls[pp.GROUP_MEANS][1].set("12; 13.5; 15; 16")
        dialog.controls[pp.COMMON_SD][1].set("5")
        dialog.controls[pp.TARGET][1].set(".85")
        setv(dialog, pp.SHOW_CURVE, True)
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-power-anova-means" + suffix + ".png")

    tools.drive_dialog(tools.AnalysisDialog, anova_case)
    app.power_planning()
    wait()
    second = len(app.runs) - 1
    assert app.runs[second].method == pp.METHOD and app.runs[second].options[pp.GROUP_MEANS] == "12; 13.5; 15; 16"
    check_oracle(second, "anova")
    assert summary(second)["Groups"] == 4
    app.layouts.append(Layout("Power layout", 2, [app.runs[first].reference, app.runs[second].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    shot(root, "window-power-layout" + suffix + ".png")
    assert app.layout_figure is not None and len(app.layout_figure.axes) >= 2
    target = out / "power-layout.png"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    assert target.stat().st_size > 1000

    # 5. Legacy recipe and the analyses of the other designs from the packet, through the dialog's own checks.
    for key in ("one_sample", "paired", "allocation_power"):
        case = CASES[key]

        def enter(dialog, case=case):
            for name, value in case.items():
                if name in dialog.controls:
                    dialog.controls[name][1].set(str(value))
            dialog.update()

        tools.drive_dialog(tools.AnalysisDialog, enter)
        app.power_planning()
        wait()
        check_oracle(len(app.runs) - 1, key)

    # The dialog of an existing analysis shows its recipe; changing the goal and the effect input recalculates.
    standardized = len(app.runs) - 1
    assert app.runs[standardized].options[pp.SIZE] == 52

    def reopen_recipe(dialog):
        assert dialog.method == pp.METHOD
        assert dialog.controls[pp.GOAL][1].get() == "Power" and dialog.controls[pp.SIZE][1].get() == "52"
        assert dialog.controls[pp.ALLOCATION][1].get() == "2:3"
        assert dialog.controls[pp.EFFECT_INPUT][1].get() == pp.STANDARDIZED_EFFECT
        assert dialog.controls[pp.STANDARDIZED_EFFECT][1].get() == "0.5"
        assert placed(dialog, pp.SIZE) and not placed(dialog, pp.TARGET) and not placed(dialog, pp.MEAN_A)
        setv(dialog, pp.GOAL, "Sample size")
        setv(dialog, pp.EFFECT_INPUT, pp.MEANS)
        for name, value in ((pp.MEAN_A, "5"), (pp.MEAN_B, "7"), (pp.COMMON_SD, "4"), (pp.TARGET, "0.8")):
            dialog.controls[name][1].set(value)

    app.show("result", standardized)
    tools.drive_dialog(tools.AnalysisDialog, reopen_recipe)
    app.edit_analysis()
    wait()
    check_oracle(standardized, "allocation")
    assert app.runs[standardized].options[pp.EFFECT_INPUT] == pp.MEANS and pp.SIZE not in app.runs[standardized].options

    # 6. Save, reopen in a clean project: recipe, sheets, points and the figure's formatting come back.
    path = directory / "power-from-summary.alab"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(path)):
        assert app.save()
    options, tables = dict(app.runs[first].options), dict(app.runs[first].result.tables)
    app.dirty = False
    app.new_project()
    app.import_file(path)
    position = next(i for i, item in enumerate(app.runs) if item.method == pp.METHOD)
    app.open_sheet(("result", position))
    wait()
    again = app.runs[position]
    assert again.options == options, again.options
    for name, table in tables.items():
        pd.testing.assert_frame_equal(again.result.tables[name], table)
    assert again.result.figure.axes[0].get_title() == "Power for A:B = 2:3"
    assert "#9b4174" in str(again.style)
    app.show("graph", position)
    root.update()
    shot(root, "window-power-reopened-graph" + suffix + ".png")
    assert app.layouts and len(app.layouts[-1].panels) == 2

    # 7. Italian: captions, tabs, choices, errors and decimal commas; the recipe stays canonical.
    def italian(dialog):
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Disegno", "Effetto", "Curva"]
        captions = {name: dialog.field_rows[name][0].cget("text") for name in (
            pp.GOAL, pp.DESIGN, pp.ALPHA, pp.TARGET, pp.ALLOCATION, pp.EFFECT_INPUT, pp.SHOW_CURVE)}
        assert captions == {pp.GOAL: "Obiettivo", pp.DESIGN: "Disegno", pp.ALPHA: "Alfa",
                            pp.TARGET: "Potenza desiderata", pp.ALLOCATION: "Allocazione A:B",
                            pp.EFFECT_INPUT: "Dati dell’effetto", pp.SHOW_CURVE: "Mostra la curva di potenza"}, captions
        shot(dialog, "window-power-design-it" + suffix + ".png")
        mode = dialog.field_rows[pp.EFFECT_INPUT][1]
        assert list(mode.cget("values")) == ["Effetto standardizzato", "Medie e deviazioni standard"]
        mode.set("Medie e deviazioni standard")
        dialog.update()
        assert dialog.controls[pp.EFFECT_INPUT][1].get() == pp.MEANS
        dialog.controls[pp.DESIGN][1].set("One-way ANOVA")
        dialog.update()
        dialog.controls[pp.GROUP_MEANS][1].set("12; ;15")
        rejected(dialog, pp.GROUP_MEANS, "è vuoto", "window-power-error-it.png", caption="Medie dei gruppi")
        dialog.controls[pp.GROUP_MEANS][1].set("12; 13,5\n15; 16")
        dialog.controls[pp.COMMON_SD][1].set("5")
        dialog.controls[pp.ALPHA][1].set("0,05")
        dialog.controls[pp.TARGET][1].set("0,85")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-power-effect-it" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        app.dirty = False
        app.new_project()
        tools.drive_dialog(tools.AnalysisDialog, italian)
        app.power_planning()
        wait()
        italian_index = len(app.runs) - 1
        assert app.runs[italian_index].options[pp.GROUP_MEANS] == "12; 13.5; 15; 16"
        assert app.runs[italian_index].options[pp.ALPHA] == 0.05
        check_oracle(italian_index, "anova")
        app.show("result", italian_index)
        root.update()
        shot(root, "window-power-result-it" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    # Leave the project tabs as they were found.
    app.dirty = False
    assert app.switch_project(home_tab)
    for key in [key for key in app.projects if key not in tabs_before]:
        app.projects[key].dirty = False
        app.remove_project_tab(key)
    assert set(app.projects) == tabs_before and app.active_project == home_tab, (set(app.projects), tabs_before)
    (out / "status.txt").write_text("PASS\n", encoding="utf-8")
