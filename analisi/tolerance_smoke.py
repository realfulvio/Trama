"""Desktop smoke check for Tolerance intervals, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_tolerance` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=tolerance-intervals python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/tolerance_093). The expected numbers of the first runs are the
frozen values of the independent reference (``expected.json``); after an edit they come from direct NumPy and SciPy
formulas written here, not from the module under test.
"""
import json
import math
import re
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import i18n, ui_theme
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .tolerance_intervals import TOLERANCE

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "tolerance_093"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
SHEET, SMALL = "Tolerance data", "Small samples"
TABLE, SETTINGS = "Tolerance intervals", "Settings"


def worksheet():
    """Group, Signal, Shifted (72 measurements in two lots) and a text column that is not a measurement."""
    frame = pd.read_csv(FIXTURES / "measurements.csv")
    frame["Remark"] = ["ok"] * len(frame)
    return frame


def small_samples():
    """Ten ordinary values, a constant column and a column with a single value."""
    return pd.DataFrame({"Few": [3.1, 3.4, 2.9, 3.8, 3.3, 3.0, 3.6, 3.2, 3.5, 3.7], "Flat": [2.0] * 10,
                         "One": [4.5] + [np.nan] * 9})


def howe(values, coverage=90.0, confidence=95.0):
    """Independent two-sided Howe limits from the sample moments and SciPy's chi-square and normal functions."""
    values = np.asarray(values, float)
    n = len(values)
    k = stats.norm.ppf((1 + coverage / 100) / 2) * math.sqrt((n - 1) * (1 + 1 / n) /
                                                             stats.chi2.ppf(1 - confidence / 100, n - 1))
    mean, sd = values.mean(), values.std(ddof=1)
    return mean - k * sd, mean + k * sd, k


def check_tolerance(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method, select_columns,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    theme = "modern" if ui_theme.is_modern() else "standard"
    out = directory / "tolerance-intervals"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]} {theme}\n", encoding="utf-8")
    suffix = f"-{theme}-{screen[0]}x{screen[1]}"
    path = directory / "tolerance-intervals.alab"
    data = worksheet()
    save_project(path, {SHEET: Dataset(data.copy()), SMALL: Dataset(small_samples())})
    app.import_file(path)
    notes = []

    def note(text):
        notes.append(text)
        (out / "checks.json").write_text(json.dumps({"theme": theme, "screen": list(screen), "checks": notes},
                                                    indent=2, ensure_ascii=False), encoding="utf-8")

    def shot(window, name):
        stem, extension = name.rsplit(".", 1)
        name = f"{stem}{suffix}.{extension}"
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
        """Run Analysis, every tab and the whole explanation lie inside the screen at the current size."""
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

    def labels_below(widget):
        """Texts of every label under ``widget``."""
        found = []
        for child in widget.winfo_children():
            try:
                found.append(str(child.cget("text")))
            except Exception:
                pass
            found.extend(labels_below(child))
        return found

    def table(index):
        return app.runs[index].result.tables[TABLE]

    def row(index, group, variable="Signal"):
        found = table(index)
        found = found[(found["Variable"] == variable) & (found["Group"] == group)]
        assert len(found) == 1, found
        return found.iloc[0]

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == TOLERANCE and app.runs[index].title == title
        return index

    def gids(index):
        return [line.get_gid() for axes in app.runs[index].result.figure.axes for line in axes.lines if line.get_gid()]

    # 1. Dialog in English: tabs, defaults, nothing preselected, the explanation, every error on its own field.
    def first_dialog(dialog):
        tools.pick_method(dialog, TOLERANCE)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Data", "Interval"]
        assert controls["Distribution"][1].get() == "Normal" and controls["Sides"][1].get() == "Two-sided"
        assert float(controls["Population coverage (%)"][1].get()) == 90.0
        assert float(controls["Confidence level (%)"][1].get()) == 95.0
        assert not controls["Show graph"][1].get()
        assert not controls["Variables"][1].curselection(), "no variable is preselected"
        explanation = [text for text in labels_below(dialog) if "confidence interval of the mean" in text]
        assert explanation and "population coverage" in explanation[0].lower(), explanation
        rejected(dialog, "Variables", "Select at least one column")
        tools.select_columns(dialog, "Variables", {"Remark"})
        message = rejected(dialog, "Variables", "must hold finite numbers")
        assert "Source row 0" in message, message
        tools.select_columns(dialog, "Variables", {"Signal", "Shifted"})
        controls["Group"][1].set("Signal")
        rejected(dialog, "Group", "not one of the variables")
        controls["Group"][1].set("Group")
        controls["Population coverage (%)"][1].set("100")
        rejected(dialog, "Population coverage (%)", "less than 100", "window-tolerance-error.png")
        controls["Population coverage (%)"][1].set("abc")
        rejected(dialog, "Population coverage (%)", "must be a number")
        controls["Population coverage (%)"][1].set("90")
        controls["Confidence level (%)"][1].set("0")
        rejected(dialog, "Confidence level (%)", "greater than 0")
        controls["Confidence level (%)"][1].set("nan")
        rejected(dialog, "Confidence level (%)", "finite")
        controls["Confidence level (%)"][1].set("95")
        controls["Show graph"][1].set(True)
        # Corrected values stay in the same dialog; every tab fits the screen and Run is reachable.
        assert controls["Group"][1].get() == "Group" and controls["Distribution"][1].get() == "Normal"
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-tolerance-dialog.png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-tolerance-interval.png")
        dialog.fields.select(0)

    normal = analyse_with(first_dialog, SHEET)
    options = app.runs[normal].options
    assert options["Variables"] == ["Signal", "Shifted"] and options["Group"] == "Group", options
    assert (options["Distribution"], options["Sides"], options["Population coverage (%)"],
            options["Confidence level (%)"], options["Show graph"]) == ("Normal", "Two-sided", 90.0, 95.0, True)
    assert list(app.runs[normal].result.tables) == [TABLE, SETTINGS]
    assert list(table(normal).columns) == ["Variable", "Group", "N", "Mean", "SD", "Lower", "Upper", "k factor",
                                           "Lower rank", "Upper rank", "Achieved confidence (%)",
                                           "Maximum confidence (%)", "Status"]
    for lot, values in EXPECTED.items():
        found, reference = row(normal, lot), values["normal"]
        assert found["N"] == reference["N"] and found["Status"] == "OK", found
        for column, key in (("Mean", "Mean"), ("SD", "SD"), ("Lower", "two_lower"), ("Upper", "two_upper"),
                            ("k factor", "k2")):
            np.testing.assert_allclose(found[column], reference[key], rtol=1e-12, err_msg=(lot, column))
        assert found["Lower rank"] is None and found["Upper rank"] is None and pd.isna(found["Maximum confidence (%)"])
    for lot in EXPECTED:                                     # Shifted: independent NumPy/SciPy formulas
        sample = data.loc[data["Group"] == lot, "Shifted"]
        low, high, factor = howe(sample)
        found = row(normal, lot, "Shifted")
        np.testing.assert_allclose([found["Lower"], found["Upper"], found["k factor"]], [low, high, factor],
                                   rtol=1e-11)
    settings = app.runs[normal].result.tables[SETTINGS]["Value"]
    assert "Howe" in settings["Method"] and settings["Group"] == "Group", settings
    app.show("result", normal)
    app.result_tabs.select(0)
    shot(root, "window-tolerance-result.png")
    app.show("graph", normal)
    root.update()
    figure = app.runs[normal].result.figure
    assert len(figure.axes) == 2 and [axes.get_title() for axes in figure.axes] == ["Signal", "Shifted"]
    assert gids(normal) == [f"tolerance-interval-{number}" for number in range(1, 5)], gids(normal)
    shot(root, "window-tolerance-graph.png")
    note("normal two-sided, grouped, two variables: reference values, tabs, errors on their own fields, graph")

    # 2. Distribution-free lower limit: ranks and order statistics; the small lot is reported, not drawn.
    def free_dialog(dialog):
        tools.pick_method(dialog, TOLERANCE)
        tools.select_columns(dialog, "Variables", {"Signal"})
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Distribution"][1].set("Distribution-free")
        dialog.controls["Sides"][1].set("Lower")
        dialog.controls["Show graph"][1].set(True)

    free = analyse_with(free_dialog, SHEET)
    lot_a, lot_b = row(free, "Lot A"), row(free, "Lot B")
    reference = EXPECTED["Lot A"]["rank"]["Lower"]["interval"]
    assert (lot_a["Lower rank"], lot_a["Lower"], lot_a["Status"]) == (reference["Lower rank"], 2.0, "OK"), lot_a
    assert lot_a["Upper rank"] is None and pd.isna(lot_a["Upper"]), lot_a
    np.testing.assert_allclose(lot_a["Achieved confidence (%)"], reference["Achieved confidence (%)"], rtol=1e-9)
    np.testing.assert_allclose(lot_a["Maximum confidence (%)"], EXPECTED["Lot A"]["rank"]["Lower"]["max"], rtol=1e-9)
    assert lot_b["Status"] == "Insufficient sample" and lot_b["N"] == 12 and pd.isna(lot_b["Lower"]), lot_b
    np.testing.assert_allclose(lot_b["Maximum confidence (%)"], EXPECTED["Lot B"]["rank"]["Lower"]["max"], rtol=1e-9)
    assert gids(free) == ["tolerance-limit-1"], gids(free)
    axes = app.runs[free].result.figure.axes[0]
    assert axes.lines[0].get_marker() == ">" and any("Insufficient sample" in t.get_text() for t in axes.texts)
    app.show("graph", free)
    root.update()
    shot(root, "window-tolerance-free-graph.png")
    note("distribution-free lower limit: ranks, achieved and maximum confidence, insufficient sample labelled")

    # 3. Small samples: three statuses on one sheet, a single drawn interval, no infinite coordinates.
    def small_dialog(dialog):
        tools.pick_method(dialog, TOLERANCE)
        tools.select_columns(dialog, "Variables", {"Few", "Flat", "One"})
        dialog.controls["Show graph"][1].set(True)

    small = analyse_with(small_dialog, SMALL)
    statuses = dict(zip(table(small)["Variable"], table(small)["Status"]))
    assert statuses == {"Few": "OK", "Flat": "Variance not measurable", "One": "Insufficient sample"}, statuses
    few = table(small).iloc[0]
    low, high, factor = howe(small_samples()["Few"])
    np.testing.assert_allclose([few["Lower"], few["Upper"], few["k factor"]], [low, high, factor], rtol=1e-11)
    assert table(small).iloc[1]["SD"] == 0.0 and pd.isna(table(small).iloc[1]["Lower"])
    assert table(small).iloc[2]["N"] == 1 and pd.isna(table(small).iloc[2]["SD"])
    assert gids(small) == ["tolerance-interval-1"]
    for axes in app.runs[small].result.figure.axes:
        for line in axes.lines:
            assert np.isfinite(np.asarray(line.get_xdata(), float)).all()
        assert all(math.isfinite(value) for value in axes.get_xlim() + axes.get_ylim())
    app.show("graph", small)
    root.update()
    shot(root, "window-tolerance-small-graph.png")
    note("small samples: three statuses, one interval drawn, finite coordinates")

    # 4. Edit a cell and exclude another: every run of the worksheet recalculates.
    app.show("data", SHEET)
    app.edit_cell(0, 1, "10.3")                      # Lot A, Signal: 1 becomes 10.3
    wait()
    signal = data.loc[data["Group"] == "Lot A", "Signal"].astype(float).to_numpy().copy()
    signal[0] = 10.3
    low, high, factor = howe(signal)
    found = row(normal, "Lot A")
    np.testing.assert_allclose([found["Lower"], found["Upper"], found["k factor"]], [low, high, factor], rtol=1e-11)
    np.testing.assert_allclose(found["Mean"], signal.mean(), rtol=1e-12)
    assert row(free, "Lot A")["Lower"] == np.sort(signal)[1], row(free, "Lot A")   # rank 2 of the edited values
    app.show("data", SHEET)
    app.current_grid.select((3, 2))                  # Lot A, Shifted, fourth row
    app.toggle_exclusion()
    wait()
    shifted = data.loc[data["Group"] == "Lot A", "Shifted"].astype(float).to_numpy()
    kept = np.delete(shifted, 3)
    low, high, factor = howe(kept)
    found = row(normal, "Lot A", "Shifted")
    assert found["N"] == 59, found
    np.testing.assert_allclose([found["Lower"], found["Upper"], found["k factor"]], [low, high, factor], rtol=1e-11)
    assert row(normal, "Lot B", "Shifted")["N"] == 12 and row(normal, "Lot A")["N"] == 60
    app.show("graph", normal)
    root.update()
    note("edit and exclusion recalculate the runs; counts and limits follow the independent formulas")

    # 5. Italian: captions, choices, messages and the explanation; canonical values in the recipe.
    original_language = i18n.active_language()
    recipe = {"Variables": ["Signal"], "Group": "Group", "Distribution": "Distribution-free", "Sides": "Upper",
              "Population coverage (%)": 90.0, "Confidence level (%)": 95.0, "Show graph": True}

    def italian(dialog):
        tools.pick_method(dialog, TOLERANCE)
        captions = {name: dialog.field_rows[name][0].cget("text")
                    for name in ("Variables", "Group", "Distribution", "Sides", "Population coverage (%)",
                                 "Confidence level (%)", "Show graph")}
        assert captions == {"Variables": "Variabili", "Group": "Gruppo", "Distribution": "Distribuzione",
                            "Sides": "Lati", "Population coverage (%)": "Copertura della popolazione (%)",
                            "Confidence level (%)": "Livello di confidenza (%)",
                            "Show graph": "Mostra grafico"}, captions
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Dati", "Intervallo"]
        distribution, sides = dialog.field_rows["Distribution"][1], dialog.field_rows["Sides"][1]
        assert list(distribution.cget("values")) == ["Normale", "Senza distribuzione"], distribution.cget("values")
        assert list(sides.cget("values")) == ["Bilaterale", "Inferiore", "Superiore"], sides.cget("values")
        assert distribution.get() == "Normale" and dialog.controls["Distribution"][1].get() == "Normal"
        assert [text for text in labels_below(dialog) if "intervallo di confidenza della media" in text]
        assert not [text for text in labels_below(dialog) if "confidence interval of the mean" in text]
        rejected(dialog, "Variables", "almeno una colonna", caption="Variabili")
        tools.select_columns(dialog, "Variables", {"Signal"})
        dialog.controls["Group"][1].set("Group")
        dialog.controls["Population coverage (%)"][1].set("100")
        rejected(dialog, "Population coverage (%)", "minore di 100", "window-tolerance-it-error.png",
                 caption="Copertura della popolazione (%)")
        dialog.controls["Population coverage (%)"][1].set("90")
        distribution.set("Senza distribuzione")
        sides.set("Superiore")
        dialog.update()
        assert dialog.controls["Distribution"][1].get() == "Distribution-free"
        assert dialog.controls["Sides"][1].get() == "Upper"
        dialog.controls["Show graph"][1].set(True)
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-tolerance-it.png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-tolerance-it-interval.png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, SHEET)
        assert app.runs[italian_index].options == recipe, app.runs[italian_index].options
        upper = row(italian_index, "Lot A")
        ordered = np.sort(signal)
        assert (upper["Upper rank"], upper["Upper"]) == (59, ordered[58]) and upper["Lower rank"] is None, upper
        assert row(italian_index, "Lot B")["Status"] == "Insufficient sample"
        app.show("result", italian_index)
        app.result_tabs.select(0)
        shot(root, "window-tolerance-it-result.png")
        app.show("graph", italian_index)
        root.update()
        assert gids(italian_index) == ["tolerance-limit-1"]
        assert app.runs[italian_index].result.figure.axes[0].lines[0].get_marker() == "<"
        shot(root, "window-tolerance-it-graph.png")
        i18n.set_language("en")

        def english_again(dialog):
            shown = [dialog.field_rows[name][1].get() for name in ("Distribution", "Sides", "Group")]
            assert shown == ["Distribution-free", "Upper", "Group"], shown
            assert dialog.field_rows["Population coverage (%)"][0].cget("text") == "Population coverage (%)"

        app.show("result", italian_index)
        tools.drive_dialog(tools.AnalysisDialog, english_again)
        app.edit_analysis()
        wait()
        assert app.runs[italian_index].options == recipe
    finally:
        i18n.set_language(original_language)
    note("Italian dialog, messages, choices and graph; English again after the switch; recipe stays canonical")

    # 6. A refused edit never replaces a valid result.
    before = app.runs[free].result
    before_table = table(free).copy()

    def bad_edit(dialog):
        dialog.controls["Confidence level (%)"][1].set("100")
        rejected(dialog, "Confidence level (%)", "less than 100")
        dialog.controls["Confidence level (%)"][1].set("95")
        tools.select_columns(dialog, "Variables", {"Remark"})
        rejected(dialog, "Variables", "must hold finite numbers")
        dialog.cancel()
        dialog.ok = lambda *args: None

    app.show("result", free)
    tools.drive_dialog(tools.AnalysisDialog, bad_edit)
    app.edit_analysis()
    wait()
    assert app.runs[free].result is before and table(free).equals(before_table)
    assert app.runs[free].options["Variables"] == ["Signal"]
    assert not errors, errors
    note("refused edits keep the previous result and options")

    # 6b. Change the coverage from Edit parameters: the same run recalculates with its new recipe.
    def wider(dialog):
        assert float(dialog.controls["Population coverage (%)"][1].get()) == 90.0
        dialog.controls["Population coverage (%)"][1].set("95")

    app.show("result", normal)
    tools.drive_dialog(tools.AnalysisDialog, wider)
    app.edit_analysis()
    wait()
    assert app.runs[normal].options["Population coverage (%)"] == 95.0, app.runs[normal].options
    low, high, factor = howe(signal, 95.0)
    found = row(normal, "Lot A")
    np.testing.assert_allclose([found["Lower"], found["Upper"], found["k factor"]], [low, high, factor], rtol=1e-11)
    low, high, factor = howe(data.loc[data["Group"] == "Lot B", "Signal"], 95.0)
    found = row(normal, "Lot B")
    np.testing.assert_allclose([found["Lower"], found["Upper"], found["k factor"]], [low, high, factor], rtol=1e-11)
    assert app.runs[normal].result.tables[SETTINGS]["Value"]["Population coverage (%)"] == 95.0
    assert "95% of the population" in app.runs[normal].result.figure._suptitle.get_text()
    assert row(free, "Lot A")["Lower"] == np.sort(signal)[1], "the other runs are untouched"
    note("changing the coverage in Edit parameters recalculates tables, settings and the figure title")

    # 7. Inspector and Format Graph on a multi-panel figure.
    app.show("graph", normal)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn groups"
    assert len(panel.elements) == 2, panel.elements              # one group per lot, drawn in both panels
    panel.select_group(panel.elements[0]["key"])
    panel.vars["element:color"].set("#9b4174")
    widget = panel.fields["color"]["widget"]
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert "#9b4174" in str(app.runs[normal].style), app.runs[normal].style
    app.toggle_inspector()
    root.update()
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Tolerance of the signal"))
    app.format_graph()
    wait()
    assert app.runs[normal].result.figure.axes[0].get_title() == "Tolerance of the signal"
    assert app.runs[normal].result.figure.axes[1].get_title() == "Shifted"
    app.show("graph", normal)
    root.update()
    shot(root, "window-tolerance-styled.png")
    note("Inspector colour and Format Graph title applied; the title edit reaches the first panel only")

    # 8. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure.
    app.show("result", normal)
    for position, name in enumerate((TABLE, SETTINGS)):
        app.result_tabs.select(position)
        target = out / f"tolerance-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == TABLE:
            assert list(exported.columns)[:3] == ["Variable", "Group", "N"] and len(exported) == 4
            assert list(exported["Status"]) == ["OK"] * 4
            np.testing.assert_allclose(exported["Mean"][1], EXPECTED["Lot B"]["normal"]["Mean"], rtol=1e-12)
        else:
            assert "Method" in exported.index
    app.show("graph", normal)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"tolerance.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension
    svg = (out / "tolerance.svg").read_text(encoding="utf-8")
    for number in range(1, 5):
        assert f'id="tolerance-interval-{number}"' in svg, number
    assert not re.search(r"\b(inf|nan)\b", " ".join(re.findall(r'd="([^"]*)"', svg))), "non-finite path data"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(out / "tolerance.pdf")
    assert "Tolerance intervals" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    assert "<image" not in svg, "the figure must stay vector"
    app.layouts.append(Layout("Tolerance panels", 2, [app.runs[normal].reference, app.runs[free].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    assert len(app.layout_figure.axes) == 2, "one panel per graph in the layout"
    shot(root, "window-tolerance-layout.png")
    for extension in ("svg", "pdf"):
        target = out / f"tolerance-layout.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        assert target.stat().st_size > 1000, extension
    layout_svg = (out / "tolerance-layout.svg").read_text(encoding="utf-8")
    assert layout_svg.lstrip().startswith(("<?xml", "<svg")) and "<image" not in layout_svg and layout_svg.count(
        "<path") >= 6, "the layout stays vector"
    assert (out / "tolerance-layout.pdf").read_bytes()[:4] == b"%PDF"
    note("CSV of both sheets, PNG, SVG with interval ids, PDF, and a two-graph layout in SVG and PDF, all vector")

    # 9. Save, reopen and open the graph before the worksheet: canonical recipes, same tables, same figure.
    def figure_state(run):
        return [(axes.get_title(), axes.get_xlabel(), tuple(round(v, 9) for v in axes.get_xlim()),
                 {line.get_gid(): np.asarray(line.get_xdata(), float).tolist() for line in axes.lines
                  if line.get_gid()}) for axes in run.result.figure.axes]

    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()},
                                        figure_state(run))
                for run in app.runs if run.method == TOLERANCE and run.result is not None}
    assert len(expected) == 4, sorted(expected)
    app.path = directory / "tolerance-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == TOLERANCE:
            app.open_sheet(("graph", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, tables, figure) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
        assert figure_state(reopened[key]) == figure, key
    key = next(k for k, v in expected.items() if v[0]["Distribution"] == "Normal" and k[0] == SHEET)
    reopened_index = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    assert reopened[key].result.figure.axes[0].get_title() == "Tolerance of the signal"
    app.show("graph", reopened_index)
    root.update()
    shot(root, "window-tolerance-reopened.png")
    note("saved .alab reopened: same recipes, tables and figures; the edit and the exclusion survived")

    # 10. Use Result as Data keeps the group, the counts and the limits as a new worksheet.
    before_tables = set(app.tables)
    app.show("result", reopened_index)
    app.result_tabs.select(0)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns)[:4] == ["Variable", "Group", "N", "Mean"] and len(frame) == 4, list(frame.columns)
    assert list(frame["N"]) == [60, 12, 59, 12], list(frame["N"])
    wait()
    assert app.pending is None and not errors, errors
    note("Use Result as Data creates the table of the intervals")
