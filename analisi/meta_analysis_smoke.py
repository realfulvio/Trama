"""Desktop smoke check for Meta-analysis of effect estimates, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_meta_analysis` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=meta-analysis python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/meta_analysis) and a generated 200-study table. The expected
numbers are the frozen package values (expected.json), never computed by the module under test, except where a step
recalculates the same recipe through the dispatcher to prove that the dialog, the worker and the saved recipe agree.
Every widget is driven through its real handler; no event is injected except ``event_generate`` on the Inspector
entry.
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, meta_analysis as meta
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "meta_analysis"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = meta.META_ANALYSIS
FOREST = "Forest plot"
RATIOS, DIFFERENCES, ZERO, LARGE, LEGACY = "Ratios", "Differences", "Zero tau", "Large", "Legacy forest"
SHEETS = ["Studies", "Pooled", "Heterogeneity", "Leave one out"]


def large_table(count=200):
    """A deterministic heterogeneous set of differences: enough omissions for Cancel to land between two of them."""
    generator = np.random.default_rng(93)
    se = generator.uniform(.08, .6, count)
    estimate = .3 + generator.normal(0, .25, count) + generator.normal(0, 1, count) * se
    return pd.DataFrame({"Study": [f"Trial {i + 1:03d}" for i in range(count)], "Estimate": estimate, "SE": se})


def check_meta_analysis(root, app, directory, tools):
    """Exercise both locales using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_meta_analysis(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_meta_analysis(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "meta-analysis"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    ratios = pd.read_csv(DATA / "ratios.csv")
    differences = pd.read_csv(DATA / "differences.csv")
    zero = pd.read_csv(DATA / "zero-tau.csv")
    legacy = ratios.assign(Lower=ratios["Estimate"] * .8, Upper=ratios["Estimate"] * 1.1)
    path = directory / "meta-analysis.alab"
    save_project(path, {RATIOS: Dataset(ratios.copy()), DIFFERENCES: Dataset(differences.copy()),
                        ZERO: Dataset(zero.copy()), LARGE: Dataset(large_table()), LEGACY: Dataset(legacy.copy())})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "language": i18n.active_language(), "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def rejected(dialog, field, contains, shot_name=None, *, caption=None):
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert (caption or field).lower() in message.lower() and contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), field
        target = dialog.initial_focus
        assert target is dialog.field_rows[field][1], "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
        return message

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def button(dialog, text):
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Button) and child.cget("text") == text:
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(dialog)

    def reachable(dialog):
        """Run Analysis, Cancel and every tab lie inside the screen at the current size."""
        dialog.update()
        for text in (i18n.ui("Run Analysis"), i18n.ui("Cancel")):
            found = button(dialog, text)
            assert found is not None and found.winfo_viewable(), text
            assert found.winfo_rooty() + found.winfo_height() <= screen[1], (text, found.winfo_rooty(), screen)
            assert found.winfo_rootx() + found.winfo_width() <= screen[0], text
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], "the dialog must fit the screen"
        dialog.fields.select(0)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def pooled(index):
        return table(index, "Pooled").iloc[0]

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    def gids(index):
        axes = app.runs[index].result.figure.axes[0]
        return {artist.get_gid() for artist in [*axes.patches, *axes.lines, *axes.collections] if artist.get_gid()}

    # 1. English dialog on the ratios: the same column for estimate and SE refused on its field, then a level out of
    # range on the second page; Ratio relabels the SE caption and highlights the log unit; random effects with
    # modified Knapp–Hartung, a prediction interval and leave one out.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Studies", "Model and output"]
        assert controls["Measure"][1].get() == "Difference" and controls["Pooling model"][1].get() == meta.COMMON
        assert not placed(dialog, "Random interval") and not placed(dialog, "Prediction interval")
        heading = dialog.field_rows["Standard error"][0]
        assert heading.cget("text") == "Standard error"
        controls["Study"][1].set("Study")
        controls["Estimate"][1].set("Estimate")
        controls["Standard error"][1].set("Estimate")
        rejected(dialog, "Standard error", "choose a column different from Estimate",
                 "window-meta-analysis-error.png")
        controls["Standard error"][1].set("SE")
        controls["Measure"][1].set("Ratio")
        dialog.update()
        assert heading.cget("text") == "SE of ln(ratio)", heading.cget("text")
        assert "NATURAL LOGARITHM" in dialog.meta_unit_note.cget("text")
        controls["Pooling model"][1].set(meta.RANDOM)
        dialog.update()
        assert placed(dialog, "Random interval") and placed(dialog, "Prediction interval")
        assert controls["Random interval"][1].get() == meta.MODIFIED_KH
        controls["Confidence level (%)"][1].set("100")
        rejected(dialog, "Confidence level (%)", "strictly between 0 and 100", "window-meta-analysis-level-error.png")
        controls["Confidence level (%)"][1].set("95")
        controls["Prediction interval"][1].set(True)
        controls["Leave one out"][1].set(True)
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-meta-analysis-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-meta-analysis-model" + suffix + ".png")
        dialog.fields.select(0)

    main = analyse_with(english, RATIOS)
    options = app.runs[main].options
    assert options == {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE", "Measure": "Ratio",
                       "Pooling model": meta.RANDOM, "Random interval": meta.MODIFIED_KH,
                       "Confidence level (%)": 95.0, "Prediction interval": True, "Leave one out": True,
                       "Show graph": True}, options
    assert list(app.runs[main].result.tables) == SHEETS, list(app.runs[main].result.tables)
    done("english dialog: same column refused on Standard error, level refused on its page, SE of ln(ratio)")
    want = EXPECTED["ratios"]
    row = pooled(main)
    for name in ("Estimate", "Lower", "Upper", "SE", "Prediction lower", "Prediction upper"):
        np.testing.assert_allclose(float(row[name]), want[name], rtol=1e-9, err_msg=name)
    assert (int(row["Studies"]), int(row["Omitted studies"])) == (5, 0)
    assert row["Prediction status"] == meta.PI_DONE, row["Prediction status"]
    heterogeneity = table(main, "Heterogeneity").iloc[0]
    for name in ("Q", "Q p", "I² (%)", "Tau²"):
        np.testing.assert_allclose(float(heterogeneity[name]), want[name], rtol=1e-9, err_msg=name)
    studies = table(main, "Studies")
    assert list(studies.columns) == meta.STUDY_COLUMNS and list(studies["Source row"]) == [1, 2, 3, 4, 5]
    assert list(studies["Study"]) == ["Cohort $", "Cohort B", "Cohort C", "Cohort B", "Cohort D"]
    np.testing.assert_allclose(studies["Weight (%)"].to_numpy(float), want["Weight (%)"], rtol=1e-9)
    np.testing.assert_allclose(studies[["Lower", "Upper"]].to_numpy(float), EXPECTED["ratio_study_limits"],
                               rtol=1e-9)
    omissions = table(main, "Leave one out")
    np.testing.assert_allclose(omissions["Estimate"].to_numpy(float), EXPECTED["omissions"], rtol=1e-9)
    assert (omissions["Status"] == meta.CALCULATED).all()
    done("ratios: pooled 1.0361080734, Tau² 0.0387770576, I² 55.81%, prediction and omissions as expected.json")

    app.show("result", main)
    app.result_tabs.select(1)
    root.update()
    shot(root, "window-meta-analysis-results" + suffix + ".png")
    app.result_tabs.select(0)
    app.show("graph", main)
    root.update()
    axes = app.runs[main].result.figure.axes[0]
    assert {meta.DIAMOND_GID, meta.REFERENCE_GID} <= gids(main), gids(main)
    assert axes.get_xscale() == "log" and getattr(axes, "_tramastat_numeric_axes", None) == ("x",)
    labels = [tick.get_text() for tick in axes.get_yticklabels()]
    assert "Cohort $" in labels and any(label.startswith("Pooled") for label in labels), labels
    assert not any(tick.get_parse_math() for tick in axes.get_yticklabels())
    shot(root, "window-meta-analysis-graph" + suffix + ".png")
    done("forest figure: pooled diamond, null reference at 1 on a log axis, literal study labels")

    # 1 (Italian). Zero heterogeneity: Italian captions and choices, a level of 0 refused on its field, then a run
    # whose recipe keeps the canonical English tokens.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
        assert captions["Pooling model"] == "Modello di sintesi", captions
        assert captions["Leave one out"] == "Omissione di uno studio alla volta", captions
        assert [dialog.fields.tab(i, "text") for i in range(2)] == ["Studi", "Modello e risultati"]
        assert list(dialog.field_rows["Pooling model"][1].cget("values")) == [
            "Effetto comune", "Effetti casuali (Paule–Mandel)"]
        for name in ("Study", "Estimate"):
            dialog.controls[name][1].set(name)
        dialog.controls["Standard error"][1].set("SE")
        dialog.field_rows["Measure"][1].set("Rapporto")
        dialog.field_rows["Measure"][1].event_generate("<<ComboboxSelected>>")
        dialog.update()
        assert dialog.field_rows["Standard error"][0].cget("text") == "ES di ln(rapporto)"
        assert "LOGARITMO NATURALE" in dialog.meta_unit_note.cget("text")
        dialog.controls["Pooling model"][1].set(meta.RANDOM)
        dialog.controls["Prediction interval"][1].set(True)
        dialog.controls["Confidence level (%)"][1].set("0")
        rejected(dialog, "Confidence level (%)", "strettamente compreso tra 0 e 100",
                 "window-meta-analysis-it-error.png", caption="Livello di confidenza (%)")
        dialog.controls["Confidence level (%)"][1].set("95")
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-meta-analysis-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-meta-analysis-it-model" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, ZERO)
        recipe = app.runs[italian_index].options
        assert recipe["Measure"] == "Ratio" and recipe["Pooling model"] == meta.RANDOM, recipe
        assert recipe["Random interval"] == meta.MODIFIED_KH and recipe["Leave one out"] is False, recipe
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-meta-analysis-it-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    want = EXPECTED["zero_tau"]
    row = pooled(italian_index)
    for name in ("Estimate", "Lower", "Upper", "Prediction lower", "Prediction upper"):
        np.testing.assert_allclose(float(row[name]), want[name], rtol=1e-9, err_msg=name)
    assert float(table(italian_index, "Heterogeneity").iloc[0]["Tau²"]) == 0.0
    done("italian dialog: level refused on its field, ES di ln(rapporto), zero Tau² as expected.json")

    # Common effect on the differences, through the dispatcher too: the dialog, the worker and the recipe agree.
    def common(dialog):
        tools.pick_method(dialog, METHOD)
        for name, column in (("Study", "Study"), ("Estimate", "Estimate"), ("Standard error", "SE")):
            dialog.controls[name][1].set(column)

    difference_index = analyse_with(common, DIFFERENCES)
    want = EXPECTED["common"]
    row = pooled(difference_index)
    for name in ("Estimate", "Lower", "Upper", "SE"):
        np.testing.assert_allclose(float(row[name]), want[name], rtol=1e-12, err_msg=name)
    assert row["Prediction status"] == meta.PI_NOT_REQUESTED, row["Prediction status"]
    direct = analyse(METHOD, differences, dict(app.runs[difference_index].options))
    for name in ("Studies", "Pooled", "Heterogeneity"):
        pd.testing.assert_frame_equal(table(difference_index, name), direct.tables[name])
    assert app.runs[difference_index].result.figure.axes[0].get_xscale() == "linear"
    done("common effect on differences equals expected.json and the dispatcher")

    # 3. Edit a value, exclude a cell, then a zero SE that reopens the dialog on its field, and the recovery.
    app.show("data", RATIOS)
    before = table(main, "Pooled").copy()
    estimate_column = app.tables[RATIOS].raw.columns.get_loc("Estimate")
    se_column = app.tables[RATIOS].raw.columns.get_loc("SE")
    app.edit_cell(0, estimate_column, "0.8")
    wait()
    changed = table(main, "Pooled")
    assert not changed.equals(before), "a valid estimate change recalculates the pooled result"
    want_frame = analyse(METHOD, app.tables[RATIOS].frame(mask_excluded=True), dict(app.runs[main].options))
    pd.testing.assert_frame_equal(changed, want_frame.tables["Pooled"])
    app.show("data", RATIOS)
    app.current_grid.select((2, se_column))
    app.toggle_exclusion()
    wait()
    row = pooled(main)
    assert (int(row["Studies"]), int(row["Omitted studies"])) == (4, 1), row
    assert list(table(main, "Studies")["Source row"]) == [1, 2, 4, 5]
    done("estimate edit and excluded SE cell recalculate; the omitted row is counted")

    app.show("result", main)
    kept_tables = {name: frame.copy() for name, frame in app.runs[main].result.tables.items()}
    kept_options = dict(app.runs[main].options)
    state = {"done": False}

    def find_dialog():
        def find(parent):
            for child in parent.winfo_children():
                if isinstance(child, tools.AnalysisDialog):
                    return child
                found = find(child)
                if found is not None:
                    return found
        return find(root)

    def recovered(tries=0):
        dialog = find_dialog()
        if dialog is None or not dialog.winfo_viewable():
            if tries > 1200:
                errors.append("the recovered AnalysisDialog did not open")
                state["done"] = True
                return
            root.after(25, lambda: recovered(tries + 1))
            return
        try:
            assert dialog.error_label is not None, "no banner"
            banner = dialog.error_label.cget("text")
            assert "source row 2 must be greater than zero" in banner, banner
            assert dialog.initial_field == "Standard error"
            assert dialog.fields.select() == page_of(dialog, "Standard error")
            assert dialog.field_rows["Standard error"][0].cget("text") == "SE of ln(ratio)"
            assert dialog.controls["Pooling model"][1].get() == meta.RANDOM
            shot(dialog, "window-meta-analysis-recovered" + suffix + ".png")
            dialog.cancel()
        except Exception as error:
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    app.show("data", RATIOS)
    root.after(25, recovered)
    app.edit_cell(1, se_column, "0")
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    assert not errors, errors
    assert app.runs[main].options == kept_options
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[main].result.tables[name], frame)
    assert app.runs[main].calculation_error and "source row 2" in app.runs[main].calculation_error
    app.show("result", main)
    assert app.stale_calculation_note() is not None, "the stale result must be flagged"
    app.show("data", RATIOS)
    app.edit_cell(1, se_column, "0.27")
    wait()
    assert app.runs[main].calculation_error is None and app.stale_calculation_note(("result", main)) is None
    done("a zero SE flags the kept result stale, reopens Standard error and recovers")

    # Cancel between leave-one-out omissions on 200 studies, then a complete restart.
    large_options = {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE", "Measure": "Difference",
                     "Pooling model": meta.RANDOM, "Random interval": meta.MODIFIED_KH,
                     "Confidence level (%)": 95.0, "Prediction interval": True, "Leave one out": True,
                     "Show graph": True}
    large = tools.Run(METHOD, LARGE, dict(large_options))
    started = time.perf_counter()
    app.add_result(large, app.compute(large, app.tables[LARGE].frame(mask_excluded=True)))
    report["large_seconds"] = round(time.perf_counter() - started, 3)
    large_index = app.runs.index(large)
    assert len(table(large_index, "Leave one out")) == 200 and int(pooled(large_index)["Studies"]) == 200
    previous = large.result
    app.show("result", large_index)
    app.recalculate(large_index)
    assert app.calculation is not None, "leave one out offers Cancel"
    app.calculation.cancel.set()
    wait()
    assert large.result is previous, "Cancel keeps the last completed result"
    assert app.status.get() == f"{METHOD} cancelled. The last completed results are kept.", app.status.get()
    app.recalculate(large_index)
    wait()
    assert large.result is not previous and not errors, errors
    pd.testing.assert_frame_equal(large.result.tables["Leave one out"], previous.tables["Leave one out"])
    app.show("graph", large_index)
    root.update()
    height = large.result.figure.get_size_inches()[1]
    assert height <= 40, height
    shot(root, "window-meta-analysis-200" + suffix + ".png")
    done(f"200 studies with leave one out in {report['large_seconds']} s; Cancel keeps the result, restart agrees")

    # 4. Format Graph and the Inspector on the forest figure; literal titles.
    app.show("graph", main)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn elements"
    report["inspector"] = [element["name"] for element in panel.elements]
    panel.select_group(panel.elements[0]["key"])
    panel.vars["element:color"].set("#9b4174")
    widget = panel.fields["color"]["widget"]
    widget.focus_force()
    root.update()
    widget.event_generate("<Return>")
    root.update()
    assert panel.apply(), panel.errors
    assert "#9b4174" in str(app.runs[main].style), app.runs[main].style
    confirmed = app.runs[main].style
    panel.vars["element:color"].set("#117733")
    widget.event_generate("<Return>")
    root.update()
    assert panel.has_draft
    panel.cancel()
    root.update()
    assert app.inspector is None and app.runs[main].style == confirmed, "Cancel restores the confirmed style"
    title = "Pooled $effect$ and _ratio_"
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set(title))
    app.format_graph()
    wait()
    axes = app.runs[main].result.figure.axes[0]
    assert axes.get_title() == title and not axes.title.get_parse_math()
    assert {meta.DIAMOND_GID, meta.REFERENCE_GID} <= gids(main), "styling keeps the stable parts"
    app.show("graph", main)
    root.update()
    shot(root, "window-meta-analysis-styled" + suffix + ".png")
    done("Inspector Apply and Cancel, Format Graph with a literal $ title")

    # Exports: CSV of each sheet, then PNG, SVG and PDF of the figure and a two-panel layout.
    app.show("result", main)
    sheets = list(app.runs[main].result.tables)
    columns = {"Studies": meta.STUDY_COLUMNS, "Pooled": meta.POOLED_COLUMNS,
               "Heterogeneity": meta.HETEROGENEITY_COLUMNS, "Leave one out": meta.LOO_COLUMNS}
    for position, name in enumerate(sheets):
        app.result_tabs.select(position)
        target = out / f"meta-analysis-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        assert list(exported.columns) == columns[name], (name, list(exported.columns))
    app.show("graph", main)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"meta-analysis.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "meta-analysis.svg").read_text(encoding="utf-8")
    assert f'id="{meta.DIAMOND_GID}' in svg and f'id="{meta.REFERENCE_GID}' in svg, "stable ids in the SVG"
    assert "<image" not in svg and "#9b4174" in svg.lower(), "the figure stays vector in the styled colour"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "meta-analysis.pdf")
    assert "Pooled" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("Meta-analysis panels", 2,
                              [app.runs[main].reference, app.runs[difference_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    target = exports / "layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    assert target.read_bytes()[:4] == b"%PDF" and target.stat().st_size > 1000
    [(_, layout_text, layout_images)] = read_pdf(target)
    assert layout_images == 0, "the two-panel layout stays vector"
    layout_svg = exports / "layout.svg"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    layout_text = layout_svg.read_text(encoding="utf-8")
    assert "<svg" in layout_text[:600] and "<image" not in layout_text
    shot(root, "window-meta-analysis-layout" + suffix + ".png")
    done("CSV of each sheet, PNG, SVG, PDF and a two-panel layout kept vector")

    # The legacy Forest plot recipe keeps its tables and draws no pooled diamond.
    forest_options = {"Input": "One study per row", "Study": "Study", "Estimate": "Estimate",
                      "Lower limit": "Lower", "Upper limit": "Upper", "Measure": "Ratio", "Scale": "Log10",
                      "Reference": 1.0}
    forest = tools.Run(FOREST, LEGACY, forest_options)
    app.add_result(forest, app.compute(forest, legacy))
    assert list(forest.result.tables) == ["Forest values", "Summary"], list(forest.result.tables)
    assert not any(part.get_gid() == meta.DIAMOND_GID for part in forest.result.figure.axes[0].patches)
    forest_before = {name: frame.copy() for name, frame in forest.result.tables.items()}

    # 5. Save, reopen with the graph first: canonical recipes, the same tables, the same Forest plot results.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method in (METHOD, FOREST)}
    assert len(expected_runs) >= 5, sorted(expected_runs)
    app.path = directory / "meta-analysis-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD:
            app.open_sheet(("graph", position))
            wait()
        elif run.method == FOREST:
            app.open_sheet(("result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    for name, frame in forest_before.items():
        pd.testing.assert_frame_equal(reopened[(LEGACY, forest.slot)].result.tables[name], frame, rtol=1e-12)
    key = next(k for k in expected_runs if k[0] == RATIOS)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    app.show("graph", position)
    root.update()
    assert app.runs[position].result.figure.axes[0].get_title() == title
    assert {meta.DIAMOND_GID, meta.REFERENCE_GID} <= gids(position)
    shot(root, "window-meta-analysis-reopened" + suffix + ".png")
    done("save and reopen from the graph; the legacy Forest plot is unchanged")

    # Use Result as Data keeps the study table.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(0)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns) == meta.STUDY_COLUMNS and len(frame) == 4, frame.columns
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    assert not errors, errors
