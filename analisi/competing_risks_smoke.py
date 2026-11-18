"""Desktop smoke check for Competing risks, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_competing_risks` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=competing-risks python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/competing_risks). The expected numbers are the frozen values
produced with cmprsk::cuminc (expected.json), never computed by the module under test, except where a step says it
recalculates the same recipe through the dispatcher to prove that the dialog, the worker and the saved recipe agree.
Every widget is driven through its real handler; no event is injected except where noted (``event_generate`` on the
Inspector entry).
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import competing_risks_workbench as cr, i18n
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "competing_risks"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = cr.COMPETING_RISKS
KM_METHOD = "Kaplan–Meier survival"
COHORTS, TIES, LEGACY = "Cohorts", "Ties", "Legacy KM"
TIMES = "0\n1\n1.5\n3\n3\n6\n6.5\n7\n8"
CURVE = "competing-risk-curve-g{group}-c{cause}"
BAND = "competing-risk-band-g{group}-c{cause}"


def check_competing_risks(root, app, directory, tools):
    """Exercise both locales using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_competing_risks(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _check_competing_risks(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "competing-risks"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    cohorts = pd.read_csv(DATA / "cohorts.csv")
    ties = pd.read_csv(DATA / "ties.csv")
    legacy = pd.read_csv(DATA / "legacy-km.csv")
    path = directory / "competing-risks.alab"
    save_project(path, {COHORTS: Dataset(cohorts.copy()), TIES: Dataset(ties.copy()), LEGACY: Dataset(legacy.copy())})
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
        assert target is not None and target.winfo_exists(), "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
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
        dialog.fields.select(0)

    def type_into(dialog, field, text):
        editor = dialog.controls[field][1]
        editor.text.delete("1.0", "end")
        editor.text.insert("1.0", text)
        dialog.update()

    def table(index, name):
        return app.runs[index].result.tables[name]

    def lines(index):
        return [line.get_gid() for line in app.runs[index].result.figure.axes[0].lines
                if str(line.get_gid()).startswith("competing-risk-curve")]

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    def edit_with(index, action, initial_field=None):
        tools.drive_dialog(tools.AnalysisDialog, action)
        app.show("result", index)
        app.edit_analysis(initial_field=initial_field)
        wait()

    def pairs(index, cause="1"):
        frame = table(index, "Gray pairwise")
        return frame[frame["Cause"].astype(str) == cause].set_index(["First", "Second"])

    # 1 and 2. English dialog: a negative time on its field, corrected in the same dialog; Gray omnibus and pairs,
    # Percent, a 90% interval, bands and requested times that coincide and fall beyond the follow-up.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Data", "Estimates", "Graph"]
        assert controls["Censor code"][1].get() == "0"
        assert controls["Event codes"][1].raw_lines() == ["1", "2"] and controls["Gray tests"][1].get() == "Off"
        assert controls["Graph"][1].get() == "Selected cause" and placed(dialog, "Graph cause")
        for name in ("Time", "Status", "Group"):
            controls[name][1].set(name)
        type_into(dialog, "Times", "-1")
        rejected(dialog, "Times", "must be a finite number of 0 or more", "window-competing-risks-error.png")
        type_into(dialog, "Times", TIMES)
        controls["Confidence level (%)"][1].set("90")
        controls["Gray tests"][1].set("Omnibus and pairwise")
        controls["Display"][1].set("Percent")
        controls["Show confidence bands"][1].set(True)
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-competing-risks-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-competing-risks-estimates" + suffix + ".png")
        dialog.fields.select(2)
        dialog.update()
        shot(dialog, "window-competing-risks-graph" + suffix + ".png")
        dialog.fields.select(0)

    main = analyse_with(english, COHORTS)
    options = app.runs[main].options
    assert options["Times"] == [0.0, 1.0, 1.5, 3.0, 3.0, 6.0, 6.5, 7.0, 8.0], options
    assert options["Confidence level (%)"] == 90.0 and options["Gray tests"] == "Omnibus and pairwise", options
    assert options["Event codes"] == ["1", "2"] and options["Censor code"] == "0" and options["Group"] == "Group"
    assert options["Display"] == "Percent" and options["Show confidence bands"] is True, options
    assert list(app.runs[main].result.tables) == [
        "Cumulative incidence", "Time estimates", "Gray tests", "Gray pairwise", "Settings"]
    done("english dialog: negative time refused on its field and corrected in the same dialog")
    expected = EXPECTED["cohorts"]
    omnibus = table(main, "Gray tests").set_index("Cause")
    np.testing.assert_allclose(float(omnibus.loc["1", "Chi square"]), 5.525404520468906, rtol=1e-9)
    np.testing.assert_allclose(float(omnibus.loc["1", "Chi square"]), expected["omnibus"][0][0], rtol=1e-12)
    np.testing.assert_allclose(float(omnibus.loc["1", "p"]), expected["omnibus"][0][2], rtol=1e-9)
    np.testing.assert_allclose(float(pairs(main).loc[("A", "B"), "Adjusted p"]), 0.07920734421939253, rtol=1e-9)
    assert expected["used"] == 27 and expected["omitted"] == 3
    settings = table(main, "Settings").set_index("Setting")["Value"]
    assert (int(settings["Complete cases"]), int(settings["Omitted cases"])) == (27, 3), settings
    estimates = table(main, "Time estimates")
    assert len(estimates) == 3 * 2 * 9, "one row per group, cause and requested time, duplicates kept"
    assert (estimates["Status"] == "Beyond follow-up").any() and (estimates["Status"] == "OK").any()
    assert (estimates[(estimates["Group"] == "A") & (estimates["Cause"].astype(str) == "1")]["Time"] == 3).sum() == 2
    done("Gray omnibus 5.5254045205, Holm p A/B 0.0792073442, requested times with duplicates and beyond follow-up")

    app.show("result", main)
    app.result_tabs.select(0)
    shot(root, "window-competing-risks-results" + suffix + ".png")
    app.show("graph", main)
    root.update()
    figure = app.runs[main].result.figure
    axes = figure.axes[0]
    assert lines(main) == [CURVE.format(group=g, cause=1) for g in (1, 2, 3)], lines(main)
    assert {c.get_gid() for c in axes.collections} >= {BAND.format(group=g, cause=1) for g in (1, 2, 3)}
    assert axes.get_ylabel() == "Cumulative incidence (%)" and 5 < axes.get_ylim()[1] <= 100, axes.get_ylim()
    assert axes.get_xlim()[0] == 0 and getattr(axes, "_tramastat_numeric_axes", None) == ("x", "y")
    shot(root, "window-competing-risks-graph" + suffix + ".png")

    # All causes: stable ids for every group and cause on the same axes, the drawn cause hidden.
    def all_causes(dialog):
        assert dialog.fields.select() == page_of(dialog, "Graph"), "Graph settings opens the Graph page"
        dialog.controls["Graph"][1].set("All causes")
        dialog.update()
        assert not placed(dialog, "Graph cause")

    edit_with(main, all_causes, "Graph")
    assert "Graph cause" not in app.runs[main].options and app.runs[main].options["Graph"] == "All causes"
    assert lines(main) == [CURVE.format(group=g, cause=c) for c in (1, 2) for g in (1, 2, 3)], lines(main)
    app.show("graph", main)
    root.update()
    axes = app.runs[main].result.figure.axes[0]
    legend = [text.get_text() for text in axes.get_legend().get_texts()]
    assert legend[:5] == ["A", "B", "C", "Cause 1", "Cause 2"], legend
    assert not any(text.get_parse_math() for text in axes.get_legend().get_texts())
    shot(root, "window-competing-risks-all-causes" + suffix + ".png")
    # Back to one cause: the drawn cause returns on the first value and keeps what the recipe holds.
    edit_with(main, lambda dialog: dialog.controls["Graph"][1].set("Selected cause"), "Graph")
    assert lines(main) == [CURVE.format(group=g, cause=1) for g in (1, 2, 3)]
    done("graph: stable ids, axes and limits, all causes and back")

    # 1 (Italian). A duplicated event code on its own field, focus reachable, then a correct run.
    original_language = i18n.active_language()

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
        assert captions["Event codes"] == "Codici dell’evento" and captions["Gray tests"] == "Test di Gray", captions
        assert [dialog.fields.tab(i, "text") for i in range(3)] == ["Dati", "Stime", "Grafico"]
        assert list(dialog.field_rows["Gray tests"][1].cget("values")) == [
            "Disattivati", "Globale (omnibus)", "Globale e a coppie"]
        for name in ("Time", "Status"):
            dialog.controls[name][1].set(name)
        type_into(dialog, "Event codes", "1\n1")
        rejected(dialog, "Event codes", "ripete un codice precedente", "window-competing-risks-it-error.png",
                 caption="Codici dell’evento")
        type_into(dialog, "Event codes", "1\n2")
        dialog.controls["Gray tests"][1].set("Omnibus")
        reachable(dialog)
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-competing-risks-it" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-competing-risks-it-estimates" + suffix + ".png")
        dialog.fields.select(0)

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, TIES)
        assert app.runs[italian_index].options["Gray tests"] == "Omnibus", "the recipe keeps the canonical token"
        assert app.runs[italian_index].options["Group"] is None
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-competing-risks-it-graph" + suffix + ".png")
        assert app.runs[italian_index].result.figure.axes[0].get_ylabel() == "Cumulative incidence"
    finally:
        i18n.set_language(original_language)
    done("italian dialog: duplicate code on its field, focus reachable, canonical recipe")

    # 3. Edit a status, exclude a cell, then an unknown status and Cancel.
    def recalculated(frame):
        masked = frame.copy()
        return analyse(METHOD, masked, dict(app.runs[main].options))

    app.show("data", COHORTS)
    before = table(main, "Cumulative incidence").copy()
    status_column = app.tables[COHORTS].raw.columns.get_loc("Status")
    time_column = app.tables[COHORTS].raw.columns.get_loc("Time")
    app.edit_cell(0, status_column, "2")
    wait()
    changed = table(main, "Cumulative incidence")
    assert not changed.equals(before), "a valid status change recalculates the estimates"
    want = recalculated(app.tables[COHORTS].frame(mask_excluded=True)).tables["Cumulative incidence"]
    pd.testing.assert_frame_equal(changed, want)
    app.show("data", COHORTS)
    app.current_grid.select((2, time_column))
    app.toggle_exclusion()
    wait()
    assert int(table(main, "Settings").set_index("Setting")["Value"]["Omitted cases"]) == 4
    done("status edit and excluded cell recalculate the estimates")

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
            assert "neither the censor code nor one of the event codes" in banner, banner
            assert dialog.initial_field == "Status"
            assert dialog.fields.select() == page_of(dialog, "Status")
            assert dialog.controls["Gray tests"][1].get() == "Omnibus and pairwise"
            assert dialog.controls["Event codes"][1].raw_lines() == ["1", "2"]
            shot(dialog, "window-competing-risks-recovered" + suffix + ".png")
            dialog.cancel()
        except Exception as error:
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    app.show("data", COHORTS)
    root.after(25, recovered)
    app.edit_cell(1, status_column, "7")
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    assert not errors, errors
    assert app.runs[main].options == kept_options
    for name, frame in kept_tables.items():
        pd.testing.assert_frame_equal(app.runs[main].result.tables[name], frame)
    assert app.runs[main].calculation_error and "neither" in app.runs[main].calculation_error
    app.show("result", main)
    assert app.stale_calculation_note() is not None, "the stale result must be flagged"
    app.show("data", COHORTS)
    app.edit_cell(1, status_column, "2")
    wait()
    assert app.runs[main].calculation_error is None and app.stale_calculation_note(("result", main)) is None
    done("an unknown status flags the kept result stale, reopens the Status field and recovers")

    app.show("result", main)
    previous = app.runs[main].result
    app.recalculate(main)
    assert app.calculation is not None, "a Gray run offers Cancel"
    app.calculation.cancel.set()
    wait()
    assert app.runs[main].result is previous, "Cancel keeps the last completed result"
    assert app.status.get() == f"{METHOD} cancelled. The last completed results are kept.", app.status.get()
    app.recalculate(main)
    wait()
    assert app.runs[main].result is not previous and not errors, errors
    pd.testing.assert_frame_equal(app.runs[main].result.tables["Gray tests"], previous.tables["Gray tests"])
    done("Cancel during a Gray calculation and a restart")

    # 4. Format Graph and the Inspector on the curve figure; literal titles.
    app.show("graph", main)
    root.update()
    app.toggle_inspector()
    root.update()
    panel = app.inspector
    assert panel is not None and panel.elements, "the Inspector must offer the drawn curves"
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
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Incidence with $weights$ and _text_"))
    app.format_graph()
    wait()
    assert app.runs[main].result.figure.axes[0].get_title() == "Incidence with $weights$ and _text_"
    app.show("graph", main)
    root.update()
    done("Inspector Apply and Cancel, Format Graph with literal text")

    # Exports: CSV of each sheet, then PNG, SVG and PDF of the figure and a two-panel layout.
    app.show("result", main)
    sheets = list(app.runs[main].result.tables)
    for position, name in enumerate(sheets):
        app.result_tabs.select(position)
        target = out / f"competing-risks-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == "Cumulative incidence":
            assert list(exported.columns) == cr.CURVE_COLUMNS, list(exported.columns)
    app.show("graph", main)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"competing-risks.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "competing-risks.svg").read_text(encoding="utf-8")
    assert svg.count("<path") >= 6 and "#9b4174" in svg.lower(), "curves are vector paths in the styled colour"
    assert "<image" not in svg, "the figure must stay vector"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "competing-risks.pdf")
    assert "Incidence with" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("Competing risks panels", 2, [app.runs[main].reference, app.runs[italian_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    target = exports / "layout.pdf"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
        app.export()
    assert target.read_bytes()[:4] == b"%PDF" and target.stat().st_size > 1000
    layout_svg = exports / "layout.svg"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    assert "<svg" in layout_svg.read_text(encoding="utf-8")[:600]
    shot(root, "window-competing-risks-layout" + suffix + ".png")
    done("CSV, PNG, SVG, PDF and a two-panel layout in vector formats")

    # A Kaplan–Meier recipe written before this method existed keeps its tables.
    km_options = {"Time": "Time", "Event columns": ["Status"], "Grouping variables": []}
    km = tools.Run(KM_METHOD, LEGACY, km_options)
    app.add_result(km, app.compute(km, legacy))
    km_before = {name: frame.copy() for name, frame in km.result.tables.items()}

    # 5. Save, reopen with the graph first: canonical recipes, the same tables, the same Kaplan–Meier results.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method in (METHOD, KM_METHOD)}
    assert len(expected_runs) >= 3, sorted(expected_runs)
    app.path = directory / "competing-risks-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD:
            app.open_sheet(("graph", position))
            wait()
        elif run.method == KM_METHOD:
            app.open_sheet(("result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
    for name, frame in km_before.items():
        pd.testing.assert_frame_equal(reopened[(LEGACY, km.slot)].result.tables[name], frame, rtol=1e-12)
    key = next(k for k in expected_runs if k[0] == COHORTS)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    app.show("graph", position)
    root.update()
    assert lines(position) == [CURVE.format(group=g, cause=1) for g in (1, 2, 3)]
    shot(root, "window-competing-risks-reopened" + suffix + ".png")
    done("save and reopen from the graph; the Kaplan–Meier project is unchanged")

    # Use Result as Data keeps the long curve table.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(0)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert list(frame.columns) == cr.CURVE_COLUMNS and len(frame) > 20, frame.columns
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
