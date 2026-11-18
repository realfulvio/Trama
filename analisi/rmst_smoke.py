"""Desktop smoke check for Restricted mean survival time, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_rmst` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=rmst python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/rmst/fixtures). The expected numbers are the frozen values of
the rational oracle (expected.json) and of the Kaplan–Meier report before this method existed (legacy-km.json), never
computed by the module under test, except where a step recalculates the same recipe through the dispatcher to prove
that the dialog, the worker and the saved recipe agree. Every widget is driven through its real handler; no event is
injected except ``event_generate`` on the Inspector entry.
"""
import json
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, rmst_workbench as rw, ui_theme
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout
from .workbench import analyse

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "rmst" / "fixtures"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
LEGACY_KM = json.loads((DATA / "legacy-km.json").read_text(encoding="utf-8"))
METHOD = rw.RMST
KM_METHOD = "Kaplan–Meier survival"
KM_OPTIONS = {"Time": "Time", "Event": "Event", "Group": "Group"}
COHORTS, COORTI, TEXT, LEGACY = "Cohorts", "Coorti", "Text status", "Legacy KM"
REFERENCE, COMPARED = "Reference", "Series $B"
IDS = ("rmst-curve-0", "rmst-curve-1", "rmst-area-0", "rmst-area-1", "rmst-horizon")
SHEETS = ["RMST", "RMST comparison", "Integration steps", "Settings"]


def check_rmst(root, app, directory, tools):
    """Exercise both languages using the supplied application and smoke helpers."""
    language = i18n.active_language()
    try:
        i18n.set_language("en")
        _check_rmst(root, app, directory, tools)
    finally:
        i18n.set_language(language)


def _polygon_area(collection):
    total = 0.0
    for path in collection.get_paths():
        x, y = path.vertices[:, 0], path.vertices[:, 1]
        total += 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    return total


def _km_sheets(result):
    return {name: json.loads(sheet.to_json(orient="split", double_precision=15))
            for name, sheet in result.tables.items()}


def _check_rmst(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(("1600x1000" if screen[0] >= 1600 and screen[1] >= 1000 else "1024x768") + "+0+0")
    root.update()
    out = directory / "rmst"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    cohorts = pd.read_csv(DATA / "cohorts.csv")
    text = pd.read_csv(DATA / "text-status.csv", dtype={"Status": object})
    path = directory / "rmst.alab"
    save_project(path, {COHORTS: Dataset(cohorts.copy()), COORTI: Dataset(cohorts.copy()),
                        TEXT: Dataset(text.copy()), LEGACY: Dataset(cohorts.copy())})
    app.import_file(path)
    report = {"screen": f"{screen[0]}x{screen[1]}", "theme": "modern" if ui_theme.is_modern() else "standard",
              "checks": []}

    def done(name):
        report["checks"].append(name)

    def shot(window, name):
        tools.capture(window, name)
        if (directory / name).exists():
            (directory / name).replace(out / name)

    def page_of(dialog, field):
        return str(dialog.field_rows[field][1].master)

    def placed(dialog, name):
        return bool(dialog.field_rows[name][1].winfo_manager())

    def rejected(dialog, field, contains, shot_name=None):
        caption = dialog.field_rows[field][0].cget("text")
        with patch.object(tools.messagebox, "showerror") as banner:
            assert dialog.validate() is False, field
        assert dialog.winfo_exists()
        message = banner.call_args.args[1]
        assert caption.lower() in message.lower() and contains in message, message
        assert dialog.fields.select() == page_of(dialog, field), field
        target = dialog.initial_focus
        assert target is dialog.field_rows[field][1], "the field to correct must hold the keyboard focus"
        assert target.winfo_ismapped() or target.winfo_viewable(), "the field to correct must be reachable"
        if shot_name:
            stem, extension = shot_name.rsplit(".", 1)
            shot(dialog, stem + suffix + "." + extension)
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
        """Run Analysis and every page lie inside the screen at the current size."""
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

    def pages(dialog, stem):
        for position in range(dialog.fields.index("end")):
            dialog.fields.select(position)
            dialog.update()
            shot(dialog, f"{stem}-{position}{suffix}.png")
        dialog.fields.select(0)

    def table(index, name):
        return app.runs[index].result.tables[name]

    def arms(index):
        return table(index, "RMST").set_index("Group")

    def contrasts(index):
        return table(index, "RMST comparison").set_index("Contrast")

    def settings(index):
        return table(index, "Settings")["Value"]

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

    def figure_ids(index):
        axes = app.runs[index].result.figure.axes[0]
        return [line.get_gid() for line in axes.lines], [c.get_gid() for c in axes.collections]

    # 1. English dialog on two cohorts: a horizon beyond the follow-up is refused on its field, corrected to 6.5.
    def english(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == [
            "Data", "Codes and estimate"]
        assert controls["Event code"][1].get() == "1" and controls["Censor code"][1].get() == "0"
        assert controls["Horizon"][1].get() == "" and float(controls["Confidence level (%)"][1].get()) == 95
        assert not placed(dialog, "Reference group"), "Reference group waits for Group"
        controls["Time"][1].set("Time")
        controls["Status"][1].set("Event")
        dialog.update()
        # One cohort, All, observed up to 9; two cohorts: the smaller maximum, 8.
        assert dialog.rmst_limit.cget("text") == "Largest usable horizon: 9.", dialog.rmst_limit.cget("text")
        controls["Group"][1].set("Group")
        dialog.update()
        assert placed(dialog, "Reference group")
        assert list(dialog.field_rows["Reference group"][1].cget("values")) == [REFERENCE, COMPARED]
        assert controls["Reference group"][1].get() == REFERENCE
        assert dialog.rmst_limit.cget("text") == "Largest usable horizon: 8.", dialog.rmst_limit.cget("text")
        controls["Horizon"][1].set("10")
        rejected(dialog, "Horizon", "is beyond the follow-up. Group Reference is observed up to 8",
                 "window-rmst-error.png")
        controls["Horizon"][1].set("6.5")
        reachable(dialog)
        pages(dialog, "window-rmst-dialog")

    main = analyse_with(english, COHORTS)
    options = app.runs[main].options
    assert options == {"Time": "Time", "Status": "Event", "Group": "Group", "Reference group": REFERENCE,
                       "Event code": "1", "Censor code": "0", "Horizon": 6.5, "Confidence level (%)": 95.0,
                       "Show graph": True}, options
    assert list(app.runs[main].result.tables) == SHEETS
    for group, frozen in EXPECTED["arms"].items():
        row = arms(main).loc[group]
        for column in ("RMST", "SE", "CI lower", "CI upper"):
            np.testing.assert_allclose(float(row[column]), frozen[column], rtol=1e-12, err_msg=column)
        assert int(row["Events through horizon"]) == frozen["Events through horizon"] and row["Status"] == "OK"
    for contrast, frozen in EXPECTED["contrasts"].items():
        for column in ("Estimate", "Inference SE", "CI lower", "CI upper", "p"):
            np.testing.assert_allclose(float(contrasts(main).loc[contrast, column]), frozen[column], rtol=1e-12)
    np.testing.assert_allclose(float(arms(main).loc[REFERENCE, "RMST"]), 77 / 18, rtol=1e-15)
    done("english dialog: horizon 10 refused on its field with the focus there, corrected to 6.5; frozen values")

    app.show("result", main)
    app.result_tabs.select(0)
    shot(root, "window-rmst-results" + suffix + ".png")
    app.show("graph", main)
    root.update()
    axes = app.runs[main].result.figure.axes[0]
    lines, collections = figure_ids(main)
    assert lines == ["rmst-curve-0", "rmst-curve-1", "rmst-horizon"] and collections == ["rmst-area-0",
                                                                                          "rmst-area-1"]
    areas = {c.get_gid(): _polygon_area(c) for c in axes.collections}
    np.testing.assert_allclose(areas["rmst-area-0"], EXPECTED["arms"][REFERENCE]["RMST"], rtol=1e-12)
    np.testing.assert_allclose(areas["rmst-area-1"], EXPECTED["arms"][COMPARED]["RMST"], rtol=1e-12)
    assert axes.get_xlim() == (0.0, 6.5) and axes.get_ylim() == (0.0, 1.0), (axes.get_xlim(), axes.get_ylim())
    legend = [entry.get_text() for entry in axes.get_legend().get_texts()]
    assert legend[:2] == [REFERENCE, COMPARED], legend
    assert not any(entry.get_parse_math() for entry in axes.get_legend().get_texts()), "group names stay literal"
    shot(root, "window-rmst-graph" + suffix + ".png")
    done("graph: stable ids, areas equal to the frozen RMST, axes 0..6.5 and 0..1, literal $ in the legend")

    # 2. Reference change: the difference changes sign and the ratio becomes its reciprocal.
    def swap(reference):
        def action(dialog):
            assert dialog.fields.select() == page_of(dialog, "Reference group")
            dialog.controls["Reference group"][1].set(reference)
        return action

    frozen = EXPECTED["contrasts"]
    edit_with(main, swap(COMPARED), "Reference group")
    assert app.runs[main].options["Reference group"] == COMPARED
    swapped = contrasts(main)
    assert list(swapped["Compared group"]) == [REFERENCE, REFERENCE], swapped
    np.testing.assert_allclose(float(swapped.loc["Difference", "Estimate"]), -frozen["Difference"]["Estimate"],
                               rtol=1e-12)
    np.testing.assert_allclose(float(swapped.loc["Difference", "CI lower"]), -frozen["Difference"]["CI upper"],
                               rtol=1e-12)
    np.testing.assert_allclose(float(swapped.loc["Difference", "p"]), frozen["Difference"]["p"], rtol=1e-12)
    np.testing.assert_allclose(float(swapped.loc["Ratio", "Estimate"]), 1 / frozen["Ratio"]["Estimate"], rtol=1e-12)
    np.testing.assert_allclose(float(swapped.loc["Ratio", "CI lower"]), 1 / frozen["Ratio"]["CI upper"], rtol=1e-12)
    np.testing.assert_allclose(float(swapped.loc["Ratio", "CI upper"]), 1 / frozen["Ratio"]["CI lower"], rtol=1e-12)
    np.testing.assert_allclose(float(swapped.loc["Ratio", "p"]), frozen["Ratio"]["p"], rtol=1e-12)
    assert list(arms(main).index) == [COMPARED, REFERENCE], "the reference comes first"
    app.show("result", main)
    app.result_tabs.select(1)
    shot(root, "window-rmst-swapped" + suffix + ".png")
    edit_with(main, swap(REFERENCE), "Reference group")
    np.testing.assert_allclose(float(contrasts(main).loc["Ratio", "Estimate"]), frozen["Ratio"]["Estimate"],
                               rtol=1e-12)
    done("reference change: difference −0.7222, ratio 1/1.1688 with reciprocal limits, same p; and back")

    # 3. Italian dialog: a horizon beyond the follow-up in Italian, corrected with the decimal comma, 6,5.
    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in dialog.controls}
        assert captions["Horizon"] == "Orizzonte" and captions["Reference group"] == "Gruppo di riferimento", captions
        assert [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))] == [
            "Dati", "Codici e stima"]
        for name, column in (("Time", "Time"), ("Status", "Event"), ("Group", "Group")):
            dialog.controls[name][1].set(column)
        dialog.update()
        assert dialog.rmst_limit.cget("text") == "Orizzonte massimo utilizzabile: 8.", dialog.rmst_limit.cget("text")
        dialog.controls["Horizon"][1].set("10")
        message = rejected(dialog, "Horizon", "supera il follow-up. Il gruppo Reference è osservato fino a 8",
                           "window-rmst-it-error.png")
        assert message.startswith("Orizzonte 10 "), message
        dialog.controls["Horizon"][1].set("6,5")
        reachable(dialog)
        pages(dialog, "window-rmst-it-dialog")

    original_language = i18n.active_language()
    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, COORTI)
        assert app.runs[italian_index].options == {**options, "Reference group": REFERENCE}, \
            "the Italian recipe keeps the canonical names and the number 6.5"
        for name in SHEETS:
            pd.testing.assert_frame_equal(table(italian_index, name), table(main, name))
        app.show("result", italian_index)
        app.result_tabs.select(0)
        shot(root, "window-rmst-it-results" + suffix + ".png")
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-rmst-it-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)
    done("italian dialog: horizon 10 refused in Italian on its field, 6,5 accepted; canonical recipe, same sheets")

    # Text codes and incomplete rows, one cohort per role missing.
    def text_codes(dialog):
        tools.pick_method(dialog, METHOD)
        for name, column in (("Time", "Time"), ("Status", "Status"), ("Group", "Cohort")):
            dialog.controls[name][1].set(column)
        dialog.controls["Event code"][1].set("event")
        dialog.controls["Censor code"][1].set("lost")
        dialog.update()
        dialog.controls["Reference group"][1].set("Ref")
        dialog.controls["Horizon"][1].set("4")

    text_index = analyse_with(text_codes, TEXT)
    for group, frozen_arm in EXPECTED["text_arms"].items():
        np.testing.assert_allclose(float(arms(text_index).loc[group, "RMST"]), frozen_arm["RMST"], rtol=1e-12)
        np.testing.assert_allclose(float(arms(text_index).loc[group, "SE"]), frozen_arm["SE"], rtol=1e-12)
    assert int(settings(text_index)["Incomplete rows"]) == 3, settings(text_index)
    done("text status codes event/lost, three incomplete rows reported")

    # 4. Edit a time, exclude a cell: the saved recipe recalculates through the worker.
    def recalculated():
        frame = app.tables[COHORTS].frame(mask_excluded=True)
        return analyse(METHOD, frame, dict(app.runs[main].options))

    app.show("data", COHORTS)
    time_column = app.tables[COHORTS].raw.columns.get_loc("Time")
    before = arms(main).copy()
    app.edit_cell(2, time_column, "1.5")  # Reference: the event at 1 moves to 1.5
    wait()
    assert app.runs[main].calculation_error is None, app.runs[main].calculation_error
    np.testing.assert_allclose(float(arms(main).loc[REFERENCE, "RMST"]) - float(before.loc[REFERENCE, "RMST"]),
                               0.5 * (1 - 5 / 6), rtol=1e-12)
    for name in SHEETS:
        pd.testing.assert_frame_equal(table(main, name), recalculated().tables[name])
    app.show("data", COHORTS)
    app.current_grid.select((3, time_column))  # Series $B: the event at time zero
    app.toggle_exclusion()
    wait()
    assert int(settings(main)["Incomplete rows"]) == 1 and int(settings(main)["Complete rows"]) == 11
    assert int(arms(main).loc[COMPARED, "N"]) == 5
    for name in SHEETS:
        pd.testing.assert_frame_equal(table(main, name), recalculated().tables[name])
    done("time edit and excluded cell recalculate the saved recipe; the excluded row counts as incomplete")

    # 5. Shrink the support: clearing the last Reference observation leaves the horizon 6.5 beyond 6. The result is
    # kept and flagged, the dialog reopens on Horizon with the reason, and 6 corrects it.
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
            dialog.update()
            assert dialog.error_label is not None, "no banner"
            banner = dialog.error_label.cget("text")
            assert "is beyond the follow-up. Group Reference is observed up to 6" in banner, banner
            assert dialog.initial_field == "Horizon"
            assert dialog.fields.select() == page_of(dialog, "Horizon")
            assert dialog.controls["Horizon"][1].get() == "6.5"
            assert dialog.rmst_limit.cget("text") == "Largest usable horizon: 6.", dialog.rmst_limit.cget("text")
            assert app.runs[main].calculation_error and "beyond the follow-up" in app.runs[main].calculation_error
            shot(dialog, "window-rmst-recovered" + suffix + ".png")
            dialog.controls["Horizon"][1].set("6")
            dialog.ok()
        except Exception as error:
            errors.append(repr(error))
            dialog.cancel()
        state["done"] = True

    app.show("data", COHORTS)
    grid = app.current_grid
    grid.select((10, 0))
    grid.select((10, len(app.tables[COHORTS].raw.columns) - 1), extend=True)
    root.after(25, recovered)
    app.clear_selection()
    deadline = time.monotonic() + 60
    while not state["done"] or app.pending is not None:
        assert time.monotonic() < deadline, "recovery did not finish"
        root.update()
        time.sleep(.02)
    wait()
    assert not errors, errors
    assert app.runs[main].options == {**kept_options, "Horizon": 6.0}, app.runs[main].options
    assert app.runs[main].calculation_error is None and app.stale_calculation_note(("result", main)) is None
    assert float(arms(main).loc[REFERENCE, "Max follow-up"]) == 6.0 and float(settings(main)["Horizon"]) == 6.0
    assert not table(main, "RMST").equals(kept_tables["RMST"])
    for name in SHEETS:
        pd.testing.assert_frame_equal(table(main, name), recalculated().tables[name])
    done("cleared last Reference row: horizon 6.5 beyond 6 flagged, dialog reopened on Horizon, corrected to 6")

    # 6. Inspector Apply and Cancel, Format Graph with literal text; styling never recalculates the estimate.
    app.show("graph", main)
    root.update()
    estimate = app.runs[main].result.tables["RMST"]
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
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("RMST with $tau$ and _text_"))
    app.format_graph()
    wait()
    assert app.runs[main].result.figure.axes[0].get_title() == "RMST with $tau$ and _text_"
    pd.testing.assert_frame_equal(app.runs[main].result.tables["RMST"], estimate)
    assert figure_ids(main) == (["rmst-curve-0", "rmst-curve-1", "rmst-horizon"], ["rmst-area-0", "rmst-area-1"])
    app.show("graph", main)
    root.update()
    shot(root, "window-rmst-styled" + suffix + ".png")
    done("Inspector Apply and Cancel, Format Graph with literal text; the estimate is not recalculated")

    # 7. Exports: CSV of each sheet, PNG, SVG and PDF of the figure and a two-panel layout.
    app.show("result", main)
    for position, name in enumerate(SHEETS):
        app.result_tabs.select(position)
        target = out / f"rmst-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
    exported = pd.read_csv(out / "rmst-0.csv", index_col=0, encoding="utf-8-sig")
    assert list(exported["Group"]) == [REFERENCE, COMPARED], exported
    app.show("graph", main)
    exports = out / "exports"
    exports.mkdir(exist_ok=True)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = exports / f"rmst.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert magic in content[:400] and len(content) > 1000, extension
    svg = (exports / "rmst.svg").read_text(encoding="utf-8")
    for gid in IDS:
        assert f'id="{gid}"' in svg, gid
    assert "#9b4174" in svg.lower(), "the styled curve keeps its colour"
    assert "<image" not in svg, "the figure must stay vector"
    from .pdf_bundle_smoke import read_pdf
    [(_, pdf_text, pdf_images)] = read_pdf(exports / "rmst.pdf")
    assert "RMST with" in pdf_text and pdf_images == 0, (pdf_text, pdf_images)
    app.layouts.append(Layout("RMST panels", 2, [app.runs[main].reference, app.runs[italian_index].reference]))
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
    layout_text = layout_svg.read_text(encoding="utf-8")
    assert "<svg" in layout_text[:600] and "<image" not in layout_text
    shot(root, "window-rmst-layout" + suffix + ".png")
    done("CSV of every sheet, PNG, SVG with the five ids, PDF without images, two-panel layout in PDF and SVG")

    # 8. A Kaplan–Meier recipe written before this method existed: its sheets equal the frozen report, and its
    # recipe reopens in the Analyze dialog unchanged.
    legacy = app.tables[LEGACY].frame(mask_excluded=True)
    km = tools.Run(KM_METHOD, LEGACY, dict(KM_OPTIONS))
    app.add_result(km, app.compute(km, legacy))
    assert _km_sheets(km.result) == LEGACY_KM["tables"], "the Kaplan–Meier report is unchanged"
    km_index = app.runs.index(km)
    edit_with(km_index, lambda dialog: None)
    reopened_km = app.runs[km_index].options  # the dialog writes the current Kaplan–Meier recipe in full
    assert (reopened_km["Time"], reopened_km["Event columns"], reopened_km["Grouping variables"]) == (
        "Time", ["Event"], ["Group"]), reopened_km
    assert _km_sheets(app.runs[km_index].result) == LEGACY_KM["tables"]
    done("legacy Kaplan–Meier sheets equal the frozen report; its recipe reopens in the dialog with the same sheets")

    # 9. Save and reopen, opening the graph before the results: canonical recipes, the same sheets.
    expected_runs = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()})
                     for run in app.runs if run.result is not None and run.method in (METHOD, KM_METHOD)}
    assert len(expected_runs) >= 4, sorted(expected_runs)
    app.path = directory / "rmst-saved.alab"
    assert app.save()
    (out / "roundtrip.alab").write_bytes(app.path.read_bytes())
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method == METHOD:
            app.open_sheet(("graph", position))
            wait()
            app.open_sheet(("result", position))
            wait()
        elif run.method == KM_METHOD:
            app.open_sheet(("result", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, saved_tables) in expected_runs.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in saved_tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-12)
    key = next(k for k in expected_runs if k[0] == COHORTS)
    position = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style)
    app.show("graph", position)
    root.update()
    assert figure_ids(position) == (["rmst-curve-0", "rmst-curve-1", "rmst-horizon"],
                                    ["rmst-area-0", "rmst-area-1"])
    assert app.runs[position].result.figure.axes[0].get_title() == "RMST with $tau$ and _text_"
    shot(root, "window-rmst-reopened" + suffix + ".png")
    done("save and reopen from the graph first: recipes, sheets, style and title kept; Kaplan–Meier unchanged")

    # 10. Use Result as Data on the RMST sheet.
    before_tables = set(app.tables)
    app.show("result", position)
    app.result_tabs.select(0)
    app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 1, created
    frame = next(iter(created.values()))
    assert {"Group", "RMST", "SE", "Status"} <= set(map(str, frame.columns)) and len(frame) == 2, frame.columns
    wait()
    assert app.pending is None and not errors, errors
    done("Use Result as Data")
    (out / "candidate-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert not errors, errors
