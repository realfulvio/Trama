"""Desktop smoke for detailed correlation, correlation against a control and two independent correlations.

``tramastat.py --smoke`` calls :func:`check_correlation_details`.
Alone: ``TRAMASTAT_SMOKE_ONLY=correlation-details python tramastat.py --smoke DIR``.

The numbers come from the frozen fixture and from the same complete pairs, not from a mocked result.
Screenshots are real window captures. A message box is patched only so a modal error cannot block the probe;
the analysis dialog itself stays open on the field that failed.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .correlation_details import CORRELATE_CONTROL, COMPARE_INDEPENDENT, adjust_p_values, correlation_statistics
from .data import Dataset, save_project
from .workbench import analyse

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "correlation_details"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
PEARSON, TIES, SPEARMAN11 = "Pearson data", "Ties", "Spearman 11"
CONTROL, LABS = "Control", "Labs"
THREE, SHORT, PERFECT = "Three groups", "Short group", "Perfect"
INDEXED, EXACT, STRESS = "Indexed", "Exact nine", "Stress 24"


def _frames():
    cases = {case["id"]: case for case in json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))}
    pearson = pd.DataFrame({"X": cases["pearson-95"]["x"], "Y": cases["pearson-95"]["y"]})
    ties = pd.read_csv(FIXTURES / "ties.csv", index_col=0)
    spearman11 = pd.read_csv(FIXTURES / "spearman-11.csv")
    control = pd.read_csv(FIXTURES / "control.csv")
    control["$x$"] = [1, 3, 2, 6, 5, 4, 8, 7]
    control["Near"] = [1, 2, 3, 4, 7, 8, 6, 5]
    control["Mild"] = [1, 2, 3, 4, 8, 6, 7, 5]
    labs = pd.read_csv(FIXTURES / "independent.csv")
    three = pd.DataFrame({
        "X": [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4],
        "Y": [1, 2, 4, 3, 4, 3, 2, 1, 1, 4, 2, 3],
        "Group": ["A", "A", "A", "A", "B", "B", "B", "B", "C", "C", "C", "C"],
        "Pair": ["A", "A", "A", "A", "B", "B", "B", "B", "A", "A", "A", "A"],
    })
    short = pd.DataFrame({
        "X": [1, 2, 3, 4, 5, 6, 7, 8],
        "Y": [1, 3, 2, 5, 4, 8, 6, 7],
        "Group": ["A", "A", "B", "B", "B", "B", "B", "B"],
        "Pair": ["A", "A", "A", "A", "B", "B", "B", "B"],
    })
    perfect = pd.DataFrame({
        "X": [1, 2, 3, 4, 1, 2, 3, 4],
        "Y": [1, 2, 3, 4, 2, 1, 4, 3],
        "Group": ["A", "A", "A", "A", "B", "B", "B", "B"],
    })
    exact = pd.read_csv(FIXTURES / "exact-nine.csv")
    stress = pd.read_csv(FIXTURES / "stress-control-24.csv")
    return {
        PEARSON: pearson, TIES: ties, SPEARMAN11: spearman11, CONTROL: control, LABS: labs,
        THREE: three, SHORT: short, PERFECT: perfect, INDEXED: pearson.copy(), EXACT: exact, STRESS: stress,
    }


def check_correlation_details(root, app, directory, tools):
    """``tools`` carries AnalysisDialog, LayoutDialog, GraphFormatDialog, capture, drive_dialog,
    pick_method, select_columns, wait_for_calculation, messagebox, filedialog and ``errors``."""
    wait, errors = tools.wait_for_calculation, tools.errors
    notes = []
    timings = []
    original_language = i18n.active_language()
    original_compute = app.compute
    original_geometry = root.geometry()
    out = directory / "correlation-details"
    out.mkdir(exist_ok=True)
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    wide = screen[0] >= 1600 and screen[1] >= 1000

    def wrapped(run, frame, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_compute(run, frame, *args, **kwargs)
        finally:
            timings.append((run.title, run.method, threading.current_thread().name, time.perf_counter() - started))

    try:
        app.compute = wrapped
        i18n.set_language("en")
        root.state("normal")
        client = _client(root, screen, (1024, 768))
        root.geometry(f"{client[0]}x{client[1]}+0+0")
        root.update()
        notes.append(f"screen {screen[0]}x{screen[1]} dpi {root.winfo_fpixels('1i'):.2f}")
        notes.append(f"client {root.winfo_width()}x{root.winfo_height()} requested {client[0]}x{client[1]}")
        notes.append(f"python {sys.version.split()[0]} tk {root.tk.call('info', 'patchlevel')}")
        notes.append(f"wide {wide}")
        frames = _frames()
        path = directory / "correlation-details.alab"
        save_project(path, {name: Dataset(frame.copy()) for name, frame in frames.items()})
        app.import_file(path)
        app.tables[INDEXED].raw.index = pd.Index([10, 20, 30, 40, 50, 60])
        app.tables[TIES].raw.index = pd.Index(pd.read_csv(FIXTURES / "ties.csv")["Source"].tolist())

        def shot(window, name):
            if sys.platform != "win32" and not os.environ.get("TRAMASTAT_SMOKE_SCREENSHOTS"):
                return
            window.attributes("-topmost", True)
            window.lift()
            window.update()
            try:
                tools.capture(window, name)
            finally:
                window.attributes("-topmost", False)
            image_path = directory / name
            if image_path.exists():
                image_path.replace(out / name)
            from PIL import Image
            image = Image.open(out / name)
            assert image.size[0] >= 200 and image.size[1] >= 200, image.size
            notes.append(f"{name} {image.size[0]}x{image.size[1]}")

        def placed(dialog, name):
            return bool(dialog.field_rows[name][1].winfo_manager())

        def button(dialog, label):
            def find(parent):
                for child in parent.winfo_children():
                    if isinstance(child, ttk.Button) and child.cget("text") == label:
                        return child
                    found = find(child)
                    if found is not None:
                        return found
            return find(dialog)

        def reachable(dialog):
            dialog.update()
            run = button(dialog, i18n.ui("Run Analysis"))
            cancel = button(dialog, i18n.ui("Cancel"))
            assert run is not None and run.winfo_viewable(), "Run Analysis"
            assert cancel is not None and cancel.winfo_viewable(), "Cancel"
            assert run.winfo_rooty() + run.winfo_height() <= screen[1], (run.winfo_rooty(), screen)
            assert cancel.winfo_rooty() + cancel.winfo_height() <= screen[1]
            assert run.winfo_rootx() + run.winfo_width() <= screen[0]
            for position in range(dialog.fields.index("end")):
                dialog.fields.select(position)
                dialog.update()
                tab = dialog.fields.nametowidget(dialog.fields.select())
                assert tab.winfo_height() > 20, "the options must remain visible"
                assert dialog.winfo_rooty() + dialog.winfo_height() <= screen[1], dialog.winfo_height()

        def rejected(dialog, field, contains):
            with patch.object(tools.messagebox, "showerror") as report:
                assert dialog.validate() is False, field
            assert dialog.winfo_exists()
            message = report.call_args.args[1]
            assert contains in message, message
            assert dialog.fields.select() == str(dialog.field_rows[field][1].master), (field, message)
            return message

        def texts(dialog):
            found = []

            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Label):
                        found.append(str(child.cget("text")))
                    walk(child)

            walk(dialog)
            return found

        def run_on(title, action):
            app.show("data", title)
            tools.drive_dialog(tools.AnalysisDialog, action)
            app.choose_analysis()
            wait()
            assert not errors, errors
            return len(app.runs) - 1

        def edit(index, action):
            app.show("result", index)
            tools.drive_dialog(tools.AnalysisDialog, action)
            app.edit_analysis()
            wait()
            assert not errors, errors

        def sheet(index, name):
            return app.runs[index].result.tables[name]

        def gids(index):
            axes = app.runs[index].result.figure.axes[0]
            return {artist.get_gid() for artist in (*axes.lines, *axes.collections) if artist.get_gid()}

        # 1. Legacy recipe, then a detailed Pearson dialog that stays open on a bad level.
        def legacy_dialog(dialog):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Method"][1].set("Pearson")
            dialog.controls["Detailed results"][1].set(False)
            dialog.update()
            assert not placed(dialog, "Alternative")
            assert not placed(dialog, "Confidence level (%)")
            dialog.controls["Alternative"][1].set("nope")
            dialog.controls["Confidence level (%)"][1].set("abc")
            assert "two-sided" in " ".join(texts(dialog)).lower() or "bilateral" in " ".join(texts(dialog)).lower()

        legacy = run_on(PEARSON, legacy_dialog)
        assert app.runs[legacy].options == {"X": "X", "Y": "Y", "Method": "Pearson", "Detailed results": False}, app.runs[legacy].options
        assert "Alternative" not in app.runs[legacy].options and "Confidence level (%)" not in app.runs[legacy].options
        base = analyse("Correlation", frames[PEARSON], {"X": "X", "Y": "Y", "Method": "Pearson"})
        assert list(sheet(legacy, "Correlation").index) == ["N", "Coefficient", "p"]
        np.testing.assert_allclose(sheet(legacy, "Correlation")["Value"].astype(float),
                                   base.tables["Correlation"]["Value"].astype(float))
        np.testing.assert_allclose(app.runs[legacy].result.figure.axes[0].collections[0].get_offsets(),
                                   base.figure.axes[0].collections[0].get_offsets())

        def detailed_dialog(dialog):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Method"][1].set("Pearson")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Alternative"][1].set("Positive")
            dialog.update()
            assert placed(dialog, "Confidence level (%)")
            dialog.controls["Confidence level (%)"][1].set("abc")
            message = rejected(dialog, "Confidence level (%)", "number")
            notes.append("level-error " + message)
            shot(dialog, "dialog-level-error-en.png")
            dialog.controls["Confidence level (%)"][1].set("90")
            dialog.controls["Y"][1].set("X")
            rejected(dialog, "Y", "different columns")
            dialog.controls["Y"][1].set("Y")
            reachable(dialog)
            dialog.fields.select(1)
            dialog.update()
            shot(dialog, "dialog-detailed-en.png")
            dialog.fields.select(0)

        detailed = run_on(PEARSON, detailed_dialog)
        got = sheet(detailed, "Correlation")["Value"]
        for key, value in EXPECTED["pearson-positive-90"].items():
            if value is None:
                assert pd.isna(got[key]), key
            elif isinstance(value, float):
                assert np.isclose(got[key], value, rtol=2e-11, atol=2e-13), (key, got[key], value)
            else:
                assert got[key] == value, (key, got[key])
        assert sheet(detailed, "Pairs")["Source row"].tolist() == [0, 1, 2, 3, 4, 5]
        assert "two-sided" in sheet(detailed, "Settings")["Value"]["Confidence intervals"]
        app.show("graph", detailed)
        root.update()
        shot(root, "graph-detailed-en.png")

        # 2. Spearman ties, three alternatives, no interval. Then n=11 falls back, and Exact is refused.
        def spearman_dialog(dialog, alternative):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Method"][1].set("Spearman")
            dialog.controls["Alternative"][1].set(alternative)
            dialog.controls["Spearman p values"][1].set("Exact")
            dialog.update()
            state = str(dialog.field_rows["Spearman p values"][1].cget("state"))
            assert state == "readonly", (state, dialog.controls["Method"][1].get(),
                                         dialog.controls["Detailed results"][1].get())

        ties_index = run_on(TIES, lambda dialog: spearman_dialog(dialog, "Two-sided"))
        p_two = float(sheet(ties_index, "Correlation")["Value"]["p"])

        def set_alternative(dialog, alternative):
            dialog.controls["Alternative"][1].set(alternative)

        edit(ties_index, lambda dialog: set_alternative(dialog, "Positive"))
        p_positive = float(sheet(ties_index, "Correlation")["Value"]["p"])
        edit(ties_index, lambda dialog: set_alternative(dialog, "Negative"))
        p_negative = float(sheet(ties_index, "Correlation")["Value"]["p"])
        assert len({p_two, p_positive, p_negative}) == 3, (p_two, p_positive, p_negative)
        assert pd.isna(sheet(ties_index, "Correlation")["Value"]["Lower"])
        assert sheet(ties_index, "Correlation")["Value"]["P method"] == "Exact"
        assert sheet(ties_index, "Ranks")["Source row"].tolist() == [101, 105, 109, 120, 121, 140, 150]
        assert np.allclose(app.runs[ties_index].result.figure.axes[0].collections[0].get_offsets()[:, 0],
                           app.tables[TIES].raw["X"])

        def spearman11_dialog(dialog):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Method"][1].set("Spearman")
            dialog.controls["Spearman p values"][1].set("Exact")
            dialog.controls["Spearman exact budget"][1].set("Standard (9 pairs)")
            rejected(dialog, "Spearman p values", "9")
            shot(dialog, "dialog-exact-budget-en.png")
            dialog.controls["Spearman p values"][1].set("Automatic")

        wide_index = run_on(SPEARMAN11, spearman11_dialog)
        wide_row = sheet(wide_index, "Correlation")["Value"]
        assert wide_row["P method"] == "Approximate" and wide_row["CI method"] == "Bonett–Wright"
        assert "budget" in wide_row["Reason"]
        assert np.isclose(wide_row["Coefficient"], EXPECTED["spearman-11-ci"]["Coefficient"])

        # 3. Kendall: the Spearman control is inactive and no interval is invented.
        def kendall_dialog(dialog):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Method"][1].set("Kendall")
            dialog.update()
            assert str(dialog.field_rows["Spearman p values"][1].cget("state")) == "disabled"
            reachable(dialog)

        kendall = run_on(TIES, kendall_dialog)
        kendall_row = sheet(kendall, "Correlation")["Value"]
        assert kendall_row["P method"] == "Kendall asymptotic"
        assert pd.isna(kendall_row["Lower"]) and "Kendall" in kendall_row["Reason"]
        assert np.isclose(kendall_row["Coefficient"], EXPECTED["kendall-ties"]["Coefficient"])

        # 4. Control: constant row kept, listwise changes N, Holm and BH change only adjusted p.
        responses = ["A", "B", "Constant", "$x$", "Near", "Mild"]

        def control_dialog(dialog, missing="Pairwise complete", adjustment="Holm"):
            tools.pick_method(dialog, CORRELATE_CONTROL)
            dialog.controls["X"][1].set("X")
            tools.select_columns(dialog, "Variables", responses)
            dialog.controls["Method"][1].set("Pearson")
            dialog.controls["Missing values"][1].set(missing)
            dialog.controls["P adjustment"][1].set(adjustment)
            dialog.controls["Show intervals"][1].set(True)
            dialog.update()
            assert "pointwise" in " ".join(texts(dialog)).lower() or "simultane" in " ".join(texts(dialog)).lower()
            reachable(dialog)
            if missing == "Pairwise complete" and adjustment == "Holm":
                shot(dialog, "dialog-control-en.png")

        control_index = run_on(CONTROL, control_dialog)
        control_table = sheet(control_index, "Correlations").set_index("Variable")
        assert control_table.loc["A", "N"] == 7 and control_table.loc["B", "N"] == 7
        assert control_table.loc["Constant", "Status"] == "Unavailable" and control_table.loc["Constant", "Reason"]
        assert pd.isna(control_table.loc["Constant", "p"])
        finite = sheet(control_index, "Correlations")
        finite = finite.loc[finite["Status"] == "Available", "p"].tolist()
        assert list(control_table.loc[control_table["Status"] == "Available", "p adjusted"]) == adjust_p_values(finite, "Holm")
        assert "$x$" in [tick.get_text() for tick in app.runs[control_index].result.figure.axes[0].get_yticklabels()]
        assert not any(tick.get_parse_math() for tick in app.runs[control_index].result.figure.axes[0].get_yticklabels())
        assert "corr:intervals" in gids(control_index)

        def set_missing(dialog):
            dialog.controls["Missing values"][1].set("Listwise complete")

        pairwise_snapshot = sheet(control_index, "Correlations").copy()
        edit(control_index, set_missing)
        listwise = sheet(control_index, "Correlations")
        assert list(listwise["N"]) == [6, 6, 6, 6, 6, 6], list(listwise["N"])
        assert list(listwise["N"]) != list(pairwise_snapshot["N"])

        def set_bh(dialog):
            dialog.controls["P adjustment"][1].set("Benjamini–Hochberg")

        holm_snapshot = listwise.copy()
        edit(control_index, set_bh)
        bh = sheet(control_index, "Correlations")
        for column in ("Coefficient", "p", "Lower", "Upper", "R²", "N"):
            pd.testing.assert_series_equal(holm_snapshot[column], bh[column], check_names=False)
        mask = holm_snapshot["Status"] == "Available"
        assert not all(np.isclose(left, right) for left, right in zip(
            holm_snapshot.loc[mask, "p adjusted"], bh.loc[mask, "p adjusted"], strict=True))
        available = bh["Status"] == "Available"
        assert list(bh.loc[available, "p adjusted"]) == adjust_p_values(bh.loc[available, "p"].tolist(), "Benjamini–Hochberg")
        assert "pointwise" in " ".join(map(str, sheet(control_index, "Settings")["Value"])).lower()

        def hide_intervals(dialog):
            dialog.controls["Show intervals"][1].set(False)

        edit(control_index, hide_intervals)
        assert "corr:coefficients" in gids(control_index) and "corr:intervals" not in gids(control_index)
        assert len(sheet(control_index, "Correlations")) == 6

        # 5. Independent groups: a valid pair, an error corrected in the same dialog, a perfect coefficient.
        def labs_dialog(dialog):
            tools.pick_method(dialog, COMPARE_INDEPENDENT)
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Group"][1].set("Group")
            assert "Fisher z" in " ".join(texts(dialog))
            reachable(dialog)
            shot(dialog, "dialog-independent-en.png")

        labs_index = run_on(LABS, labs_dialog)
        assert sheet(labs_index, "Groups")["Group"].tolist() == ["Lab A", "Lab B"]
        assert len(sheet(labs_index, "Pairs")) == len(frames[LABS])
        assert "Fisher z difference" in sheet(labs_index, "Settings")["Value"]["Comparison interval"]
        assert sheet(labs_index, "Comparison")["Value"]["Status"] == "Available"

        def correct_group(dialog, contains, shot_name=None):
            tools.pick_method(dialog, COMPARE_INDEPENDENT)
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Group"][1].set("Group")
            message = rejected(dialog, "Group", contains)
            notes.append("group-error " + message)
            if shot_name:
                shot(dialog, shot_name)
            dialog.controls["Group"][1].set("Pair")

        run_on(THREE, lambda dialog: correct_group(dialog, "two", "dialog-third-group-en.png"))
        assert app.runs[-1].options["Group"] == "Pair"
        assert sheet(len(app.runs) - 1, "Groups")["Group"].tolist() == ["A", "B"]
        run_on(SHORT, lambda dialog: correct_group(dialog, "four"))
        assert "four" in notes[-1]

        perfect_index = run_on(PERFECT, lambda dialog: (
            tools.pick_method(dialog, COMPARE_INDEPENDENT),
            dialog.controls["X"][1].set("X"),
            dialog.controls["Y"][1].set("Y"),
            dialog.controls["Group"][1].set("Group"),
        ))
        assert sheet(perfect_index, "Groups").loc[0, "Coefficient"] == 1
        assert sheet(perfect_index, "Comparison")["Value"]["Status"] == "Unavailable"
        assert pd.isna(sheet(perfect_index, "Comparison")["Value"]["p"])
        legend = app.runs[perfect_index].result.figure.axes[0].get_legend()
        assert legend is not None and "Fisher z" in legend.get_title().get_text()

        # 6. Edit X, exclude a Y, undo both. Source row keeps the original index.
        def indexed_dialog(dialog):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Method"][1].set("Pearson")

        indexed = run_on(INDEXED, indexed_dialog)
        assert sheet(indexed, "Pairs")["Source row"].tolist() == [10, 20, 30, 40, 50, 60]
        original_r = float(sheet(indexed, "Correlation")["Value"]["Coefficient"])
        app.show("data", INDEXED)
        app.edit_cell(0, 0, "8")
        wait()
        assert sheet(indexed, "Pairs")["Source row"].tolist() == [10, 20, 30, 40, 50, 60]
        assert not np.isclose(sheet(indexed, "Correlation")["Value"]["Coefficient"], original_r)
        app.current_grid.active_cell = (2, 1)
        app.toggle_exclusion()
        wait()
        assert sheet(indexed, "Pairs")["Source row"].tolist() == [10, 20, 40, 50, 60]
        app.apply_worksheet_history()
        wait()
        assert sheet(indexed, "Pairs")["Source row"].tolist() == [10, 20, 30, 40, 50, 60]
        app.apply_worksheet_history()
        wait()
        assert np.isclose(sheet(indexed, "Correlation")["Value"]["Coefficient"], original_r)
        assert app.runs[indexed].options["Detailed results"] is True

        # 7. Italian dialog, save, reopen in English with the graph first, then the reverse.
        i18n.set_language("it")

        def italian_dialog(dialog):
            assert dialog.fields.tab(0, "text") == i18n.ui("Variables")
            assert any("bilaterali" in text for text in texts(dialog)), texts(dialog)
            assert dialog.choice_bindings["Alternative"].display.get() == "Positiva"
            assert dialog.controls["Alternative"][1].get() == "Positive"
            dialog.controls["Confidence level (%)"][1].set("0")
            message = rejected(dialog, "Confidence level (%)", "0 e 100")
            notes.append("level-it " + message)
            shot(dialog, "dialog-detailed-it.png")
            dialog.controls["Confidence level (%)"][1].set("90")
            assert dialog.controls["Confidence level (%)"][1].get() in {"90", "90.0"}

        edit(detailed, italian_dialog)
        assert app.runs[detailed].options["Alternative"] == "Positive"
        assert app.runs[detailed].options["Confidence level (%)"] == 90
        saved = directory / "correlation-it.alab"
        app.path = saved
        assert app.save()
        i18n.set_language("en")
        app.import_file(saved)
        reopened = next(index for index, run in enumerate(app.runs)
                        if run.title == PEARSON and run.options.get("Detailed results") is True)
        app.show("graph", reopened)
        if app.runs[reopened].result is None:
            app.recalculate(reopened)
            wait()
        shot(root, "graph-reopened-en.png")

        def english_dialog(dialog):
            assert dialog.controls["Alternative"][1].get() == "Positive"
            assert dialog.controls["Method"][1].get() == "Pearson"
            assert dialog.controls["Detailed results"][1].get() is True
            assert dialog.choice_bindings["Alternative"].display.get() == "Positive"

        edit(reopened, english_dialog)
        assert app.runs[reopened].options == app.runs[reopened].options
        canonical = dict(app.runs[reopened].options)
        assert canonical["Alternative"] == "Positive" and "Bilaterale" not in str(canonical)
        i18n.set_language("en")
        english_path = directory / "correlation-en.alab"
        app.path = english_path
        assert app.save()
        i18n.set_language("it")
        app.import_file(english_path)
        reopened = next(index for index, run in enumerate(app.runs)
                        if run.title == PEARSON and run.options.get("Detailed results") is True)
        app.show("graph", reopened)
        if app.runs[reopened].result is None:
            app.recalculate(reopened)
            wait()

        def italian_again(dialog):
            assert dialog.fields.tab(0, "text") == "Variabili"
            assert dialog.controls["Alternative"][1].get() == "Positive"
            assert dialog.choice_bindings["Alternative"].display.get() == "Positiva"

        edit(reopened, italian_again)
        assert app.runs[reopened].options["Confidence level (%)"] == 90
        i18n.set_language("en")

        # 8. Export, use the pairs as data, layout, Inspector and Format Graph.
        detailed = reopened
        app.show("result", detailed)
        app.result_tabs.select(list(app.runs[detailed].result.tables).index("Pairs"))
        exported = out / "pairs.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(exported)):
            app.export()
        loaded = pd.read_csv(exported, index_col=0)
        assert "Source row" in loaded.columns
        before_tables = set(app.tables)
        app.use_result_as_data()
        root.update()
        created = set(app.tables) - before_tables
        assert created, created
        used = app.tables[created.pop()].frame()
        assert "Source row" in used.columns and len(used) == 6

        control_index = next(index for index, run in enumerate(app.runs) if run.method == CORRELATE_CONTROL)
        if app.runs[control_index].result is None:
            app.show("graph", control_index)
            app.recalculate(control_index)
            wait()
        coefficients = sheet(control_index, "Correlations")["Coefficient"].tolist()
        options_before = dict(app.runs[control_index].options)
        app.show("graph", control_index)
        root.update()
        app.toggle_inspector()
        root.update()
        inspector = app.inspector
        assert inspector is not None
        axes = app.runs[control_index].result.figure.axes[0]
        original_title = axes.get_title()
        inspector.vars["title"].set("Not applied")
        inspector._now("title")
        assert axes.get_title() == "Not applied"
        inspector.discard()
        assert axes.get_title() == original_title
        inspector.vars["title"].set("Control correlations")
        inspector._now("title")
        assert inspector.apply() is True
        assert app.runs[control_index].options == options_before
        app.toggle_inspector()

        def format_graph(dialog):
            dialog.inputs["title"].set("Control correlations")

        tools.drive_dialog(tools.GraphFormatDialog, format_graph)
        app.format_graph()
        assert axes.get_title() == "Control correlations"
        fresh = sheet(control_index, "Correlations")["Coefficient"].tolist()
        assert len(fresh) == len(coefficients)
        for before, after in zip(coefficients, fresh, strict=True):
            assert (pd.isna(before) and pd.isna(after)) or np.isclose(before, after), (before, after)
        assert app.runs[control_index].options == options_before
        graph_png, graph_svg, graph_pdf = out / "control.png", out / "control.svg", out / "control.pdf"
        for target, marker in ((graph_png, b"\x89PNG"), (graph_svg, b"<svg"), (graph_pdf, b"%PDF")):
            with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
                app.export()
            payload = target.read_bytes()
            assert payload.startswith(marker) or marker in payload[:300], target.name
        assert "$x$" in graph_svg.read_text(encoding="utf-8")

        def choose_panels(dialog):
            wanted = [index for index, run in enumerate(dialog.runs)
                      if run is app.runs[detailed] or run is app.runs[control_index]]
            assert len(wanted) == 2, wanted
            dialog.name.set("Correlation figure")
            dialog.list.selection_clear(0, "end")
            for index in wanted:
                dialog.list.selection_set(index)
            dialog.add_selected()

        app.show("graph", detailed)
        tools.drive_dialog(tools.LayoutDialog, choose_panels)
        app.new_layout()
        wait()
        assert len(app.layout_figure.axes) == 2
        shot(root, "layout-two-panels.png")

        # 9. Exact n=9 and 24 responses stay on the worker. Then the wide viewport, when it fits.
        def exact_dialog(dialog):
            tools.pick_method(dialog, "Correlation")
            dialog.controls["X"][1].set("X")
            dialog.controls["Y"][1].set("Y")
            dialog.controls["Detailed results"][1].set(True)
            dialog.controls["Method"][1].set("Spearman")
            dialog.controls["Spearman p values"][1].set("Exact")

        exact_index = run_on(EXACT, exact_dialog)
        assert sheet(exact_index, "Correlation")["Value"]["P method"] == "Exact"
        assert int(sheet(exact_index, "Correlation")["Value"]["N"]) == 9

        def stress_dialog(dialog):
            tools.pick_method(dialog, CORRELATE_CONTROL)
            dialog.controls["X"][1].set("X")
            tools.select_columns(dialog, "Variables", [f"Y{number:02d}" for number in range(1, 25)])
            dialog.controls["Method"][1].set("Pearson")
            dialog.controls["P adjustment"][1].set("Holm")
            reachable(dialog)

        stress_index = run_on(STRESS, stress_dialog)
        assert len(sheet(stress_index, "Correlations")) == 24
        assert "Available" in set(sheet(stress_index, "Correlations")["Status"])
        assert all(name.startswith("Trama") for _, _, name, _ in timings), timings
        exact_time = next(elapsed for title, _, _, elapsed in timings if title == EXACT)
        stress_time = next(elapsed for title, _, _, elapsed in timings if title == STRESS)
        notes.append(f"exact-n9 {exact_time:.3f}s worker")
        notes.append(f"stress-24 {stress_time:.3f}s worker")

        if wide:
            root.geometry("1600x1000+0+0")
            root.update()
            notes.append(f"wide-client {root.winfo_width()}x{root.winfo_height()}")

            def wide_dialog(dialog):
                assert dialog.controls["Detailed results"][1].get() is True
                reachable(dialog)
                shot(dialog, "dialog-detailed-1600.png")

            edit(detailed, wide_dialog)
            app.show("graph", detailed)
            root.update()
            shot(root, "graph-detailed-1600.png")
        else:
            notes.append("1600x1000 not available on this display")
        (out / "notes.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    finally:
        app.compute = original_compute
        i18n.set_language(original_language)
        root.attributes("-topmost", False)
        root.geometry(original_geometry)
        root.update()


def _client(root, screen, requested):
    """Fit the requested client inside the work area of a short Windows desktop."""
    if sys.platform != "win32" or screen[1] > requested[1] + 80:
        return requested
    import ctypes
    from ctypes import wintypes
    root.update()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    outer, work = wintypes.RECT(), wintypes.RECT()
    assert user32.GetWindowRect(int(root.wm_frame(), 0), ctypes.byref(outer))
    assert user32.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)
    border_width = outer.right - outer.left - root.winfo_width()
    border_height = outer.bottom - outer.top - root.winfo_height()
    return (min(requested[0], work.right - work.left - border_width),
            min(requested[1], work.bottom - work.top - border_height))
