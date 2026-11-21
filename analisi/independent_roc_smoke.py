"""Desktop smoke check for Compare independent ROC curves, driving the real Analyze dialog and the real app.

``tramastat.py --smoke`` calls :func:`check_independent_roc` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=independent-roc python tramastat.py --smoke DIR``.

Synthetic data only: the packaged fixtures (tests/data/independent_roc). The frozen numbers of
``expected.json`` come from an exact-fraction oracle that does not use the module under test.
"""
import json
import time
from contextlib import contextmanager
from threading import Event
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n, ui_theme
from . import independent_roc as engine
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .presentation import Layout, compose_layout

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "data" / "independent_roc"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
METHOD = engine.METHOD
COHORTS, TIES, CONSTANT, LARGE, FEW = "Cohorts", "Ties", "Constant", "Large", "Few"
SEED = 20261118
HIGHER, LOWER = engine.HIGHER, engine.LOWER
SUMMARY = ("Area A", "Area B", "Raw area A", "Raw area B", "Difference", "Variance of difference", "SE", "Lower",
           "Upper", "Z", "p")
COUNTS = ("Control A N", "Patient A N", "Control B N", "Patient B N")


def large_sheet():
    """Four columns of 500 values: 2,000 observations, so that a bootstrap needs many blocks."""
    rng = np.random.default_rng(7)
    return pd.DataFrame({"C1": rng.normal(0, 1, 500), "P1": rng.normal(.8, 1, 500),
                         "C2": rng.normal(0, 1, 500), "P2": rng.normal(.5, 1, 500)})


def mann_whitney(controls, patients):
    """Probability that a patient scores above a control (half credit for ties), straight from the pairs."""
    controls, patients = np.asarray(controls, float), np.asarray(patients, float)
    greater = (patients[:, None] > controls[None, :]).sum() + .5 * (patients[:, None] == controls[None, :]).sum()
    return greater / (len(controls) * len(patients))


def check_independent_roc(root, app, directory, tools):
    """``tools`` carries the smoke helpers: AnalysisDialog, capture, drive_dialog, pick_method,
    wait_for_calculation, messagebox, filedialog and the shared ``errors`` list."""
    language, geometry = i18n.active_language(), root.geometry()
    try:
        i18n.set_language("en")
        _check_independent_roc(root, app, directory, tools)
    finally:
        i18n.set_language(language)
        root.geometry(geometry)


def _check_independent_roc(root, app, directory, tools):
    wait, errors = tools.wait_for_calculation, tools.errors
    screen = root.winfo_screenwidth(), root.winfo_screenheight()
    width, height = min(1600, screen[0] - 32), min(1000, screen[1] - 100)
    root.geometry(f"{width}x{height}+12+12")
    root.update()
    out = directory / "independent-roc"
    out.mkdir(exist_ok=True)
    (out / "screen.txt").write_text(f"{screen[0]}x{screen[1]}\n", encoding="utf-8")
    (out / "theme.txt").write_text(("modern" if ui_theme.is_modern() else "standard") + "\n", encoding="utf-8")
    suffix = f"-{screen[0]}x{screen[1]}" if screen[0] >= 1600 else ""
    path = directory / "independent-roc.alab"
    cohorts = pd.read_csv(FIXTURES / "cohorts.csv")
    save_project(path, {COHORTS: Dataset(cohorts.copy()),
                        TIES: Dataset(pd.read_csv(FIXTURES / "tied.csv")),
                        CONSTANT: Dataset(pd.read_csv(FIXTURES / "degenerate.csv")),
                        LARGE: Dataset(large_sheet()),
                        FEW: Dataset(pd.DataFrame({"C_A": [1.0, 2.0, 3.5], "P_A": [2.0, 3.0, 4.5], "C_B": [1.5, 2.5, 3.0],
                                                   "P_B": [2.5, 3.5, 1.0]}))})
    app.import_file(path)

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

    def table(index, name):
        return app.runs[index].result.tables[name]

    def summary_frame(index):
        return table(index, engine.SUMMARY_SHEET)

    def summary(index):
        return summary_frame(index).iloc[0]

    def assert_oracle(index, name):
        row, expected = summary(index), EXPECTED[name]["ROC comparison"][0]
        for column in SUMMARY:
            if expected.get(column) is None:
                assert pd.isna(row[column]), (name, column, row[column])
            else:
                np.testing.assert_allclose(row[column], expected[column], rtol=1e-12, atol=1e-15,
                                           err_msg=f"{name} {column}")
        for column in COUNTS:
            assert row[column] == expected[column], (name, column)
        for sheet, key in ((engine.CURVE_A_SHEET, "ROC curve A"), (engine.CURVE_B_SHEET, "ROC curve B")):
            frame = table(index, sheet)
            want = pd.DataFrame(EXPECTED[name][key])
            assert len(frame) == len(want), (name, sheet)
            np.testing.assert_allclose(frame["False positive rate"], want["False positive rate"], atol=1e-15)
            np.testing.assert_allclose(frame["True positive rate"], want["True positive rate"], atol=1e-15)
            np.testing.assert_allclose(frame["Threshold"].iloc[1:].astype(float),
                                       want["Threshold"].iloc[1:].astype(float))
            assert pd.isna(frame["Threshold"].iloc[0]), (name, sheet)
        if "ROC bootstrap" in EXPECTED[name]:
            # The oracle replays the same generator, so every replicate must match, not only the interval.
            frame, want = table(index, engine.BOOTSTRAP_SHEET), pd.DataFrame(EXPECTED[name]["ROC bootstrap"])
            assert len(frame) == len(want), name
            for column in ("Area A", "Area B"):
                np.testing.assert_allclose(frame[column], want[column], rtol=1e-12, atol=1e-15, err_msg=name)

    def analyse_with(dialog_action, title):
        app.show("data", title)
        tools.drive_dialog(tools.AnalysisDialog, dialog_action)
        app.choose_analysis()
        wait()
        index = len(app.runs) - 1
        assert app.runs[index].method == METHOD and app.runs[index].title == title
        return index

    def columns(dialog, control_a="C_A", patient_a="P_A", control_b="C_B", patient_b="P_B"):
        for name, column in zip(engine.COLUMN_FIELDS, (control_a, patient_a, control_b, patient_b), strict=True):
            dialog.controls[name][1].set(column)

    def gids(axes):
        return {child.get_gid() for child in axes.get_children() if child.get_gid()}

    def assert_cutoff(index, cutoff):
        """The band and the dotted line mark exactly the Maximum FPR of the recipe."""
        axes = app.runs[index].result.figure.axes[0]
        band = next(child for child in axes.get_children() if child.get_gid() == "independent-roc:band")
        line = next(child for child in axes.lines if child.get_gid() == "independent-roc:cutoff")
        assert abs(band.get_x()) < 1e-12 and abs(band.get_width() - cutoff) < 1e-12, (band.get_x(), band.get_width())
        assert [float(value) for value in line.get_xdata()] == [cutoff, cutoff], line.get_xdata()

    # 1. Full area, DeLong: defaults, hidden fields, every invalid value on its own field in the same dialog.
    def full_dialog(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        assert [dialog.fields.tab(i, "text") for i in range(2)][1] == "Area and inference", [
            dialog.fields.tab(i, "text") for i in range(2)]
        assert (controls["Direction A"][1].get(), controls["Direction B"][1].get()) == (HIGHER, HIGHER)
        assert controls["Area"][1].get() == "Full" and controls["Inference"][1].get() == "DeLong"
        assert float(controls["Confidence level (%)"][1].get()) == 95
        assert not placed(dialog, "Maximum FPR") and not placed(dialog, "Bootstrap replicates")
        assert not placed(dialog, "Bootstrap seed") and not placed(dialog, "Save bootstrap")
        assert [controls[name][1].get() for name in engine.COLUMN_FIELDS] == ["C_A", "P_A", "C_B", "P_B"], "the first four columns are proposed"
        controls["Control A"][1].set("")
        rejected(dialog, "Control A", "Choose a column")
        columns(dialog, "C_A", "C_A", "C_B", "P_B")
        rejected(dialog, "Patient A", "already used for Control A")
        columns(dialog, "C_A", "P_A", "C_B", "P_A")
        rejected(dialog, "Patient B", "already used for Patient A", "window-independent-roc-error.png")
        columns(dialog)
        controls["Direction B"][1].set(LOWER)
        controls["Confidence level (%)"][1].set("100")
        rejected(dialog, "Confidence level (%)", "greater than 0 and less than 100")
        controls["Confidence level (%)"][1].set("abc")
        rejected(dialog, "Confidence level (%)", "must be a number")
        controls["Confidence level (%)"][1].set("95")
        # Corrected values stay in the same dialog; every tab fits the screen and Run is reachable.
        assert controls["Control A"][1].get() == "C_A" and controls["Direction B"][1].get() == LOWER
        reachable(dialog)
        dialog.fields.select(0)
        shot(dialog, "window-independent-roc-dialog" + suffix + ".png")
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-independent-roc-area" + suffix + ".png")
        dialog.fields.select(0)

    full_index = analyse_with(full_dialog, COHORTS)
    options = app.runs[full_index].options
    assert options == {"Control A": "C_A", "Patient A": "P_A", "Control B": "C_B", "Patient B": "P_B",
                       "Direction A": HIGHER, "Direction B": LOWER, "Area": "Full", "Inference": "DeLong",
                       "Confidence level (%)": 95.0}, options
    assert_oracle(full_index, "full")
    assert set(app.runs[full_index].result.tables) == {engine.SUMMARY_SHEET, engine.CURVE_A_SHEET, engine.CURVE_B_SHEET}
    row = summary(full_index)
    assert row["Status"] == engine.STATUS_DELONG and row["Area type"] == "Full", row
    app.show("result", full_index)
    app.result_tabs.select(0)
    shot(root, "window-independent-roc-result" + suffix + ".png")
    app.show("graph", full_index)
    root.update()
    axes = app.runs[full_index].result.figure.axes[0]
    assert "AUC" in axes.get_title() and axes.get_xlabel() == "False positive rate"
    assert {"independent-roc:curve-a", "independent-roc:curve-b", "independent-roc:diagonal"} <= gids(axes), gids(axes)
    assert "independent-roc:band" not in gids(axes) and "independent-roc:cutoff" not in gids(axes)
    shot(root, "window-independent-roc-graph" + suffix + ".png")

    # Title and legend styling belong to the run: they must survive every recalculation below.
    def style_figure(dialog):
        dialog.inputs["title"].set("AUC of two markers")
        dialog.appearance["legend_size"].set("13")
        dialog.appearance["legend"].set("upper left")

    tools.drive_dialog(GraphFormatDialog, style_figure)
    app.format_graph()
    wait()

    def styled(index):
        axes = app.runs[index].result.figure.axes[0]
        legend = axes.get_legend()
        assert axes.get_title() == "AUC of two markers" and axes.get_xlabel() == "False positive rate", (
            axes.get_title(), axes.get_xlabel())
        assert {"independent-roc:curve-a", "independent-roc:curve-b"} <= gids(axes), gids(axes)
        assert legend is not None and legend.get_texts()[0].get_fontsize() == 13, legend
        assert app.runs[index].style["legend"] == "upper left", app.runs[index].style

    styled(full_index)
    app.show("graph", full_index)
    root.update()
    shot(root, "window-independent-roc-styled" + suffix + ".png")

    # 2. Partial area on tied scores: choosing it proposes the bootstrap; hidden values are neither validated nor saved.
    def partial_dialog(dialog):
        tools.pick_method(dialog, METHOD)
        controls = dialog.controls
        columns(dialog)
        controls["Area"][1].set("Partial")
        dialog.update()
        assert controls["Inference"][1].get() == "Percentile bootstrap", "a partial area proposes the bootstrap"
        for name in ("Maximum FPR", "Bootstrap replicates", "Bootstrap seed", "Save bootstrap"):
            assert placed(dialog, name), name
        controls["Inference"][1].set("DeLong")
        rejected(dialog, "Inference", "no DeLong variance")
        controls["Inference"][1].set("Percentile bootstrap")
        for bad in ("0", "1", "-0.1", "1,5", "abc", "nan"):
            controls["Maximum FPR"][1].set(bad)
            rejected(dialog, "Maximum FPR", "greater than 0 and less than 1")
        controls["Maximum FPR"][1].set("0,35")
        controls["Confidence level (%)"][1].set("90")
        for bad in ("199", "10001", "1,5", "abc"):
            controls["Bootstrap replicates"][1].set(bad)
            rejected(dialog, "Bootstrap replicates", "whole number from 200 to 10,000")
        controls["Bootstrap replicates"][1].set("200")
        for bad in ("-1", "4294967296", "1.5", "abc"):
            controls["Bootstrap seed"][1].set(bad)
            rejected(dialog, "Bootstrap seed", "whole number from 0 to 4,294,967,295")
        controls["Bootstrap seed"][1].set(str(SEED))
        controls["Save bootstrap"][1].set(True)
        reachable(dialog)
        dialog.fields.select(1)
        dialog.update()
        shot(dialog, "window-independent-roc-partial" + suffix + ".png")
        dialog.fields.select(0)

    partial_index = analyse_with(partial_dialog, TIES)
    options = app.runs[partial_index].options
    assert options["Area"] == "Partial" and options["Maximum FPR"] == 0.35 and options["Bootstrap replicates"] == 200
    assert options["Bootstrap seed"] == SEED and options["Save bootstrap"] is True and options[
        "Confidence level (%)"] == 90.0, options
    assert_oracle(partial_index, "partial")
    row = summary(partial_index)
    assert row["Status"] == engine.STATUS_BOOTSTRAP and row["Maximum FPR"] == 0.35 and pd.isna(row["Z"]), row
    sheet = table(partial_index, engine.BOOTSTRAP_SHEET)
    assert list(sheet.columns) == ["Replicate", "Area A", "Area B", "Difference"] and sheet["Replicate"].iloc[0] == 1
    app.show("result", partial_index)
    app.result_tabs.select(3)
    shot(root, "window-independent-roc-bootstrap" + suffix + ".png")
    app.show("graph", partial_index)
    root.update()
    axes = app.runs[partial_index].result.figure.axes[0]
    assert "pAUC" in axes.get_title() and {"independent-roc:band", "independent-roc:cutoff"} <= gids(axes), gids(axes)
    assert_cutoff(partial_index, 0.35)
    shot(root, "window-independent-roc-partial-graph" + suffix + ".png")

    # 3. Standardized partial and a cutoff on the first diagonal segment, by editing the recipe; the sheet of
    #    replicates is optional.
    def standardized(dialog):
        tools.pick_method(dialog, METHOD)
        columns(dialog)
        dialog.controls["Area"][1].set("Standardized partial")
        assert dialog.controls["Inference"][1].get() == "Percentile bootstrap"
        for name, value in (("Maximum FPR", "0.35"), ("Confidence level (%)", "90"), ("Bootstrap replicates", "200"),
                            ("Bootstrap seed", str(SEED))):
            dialog.controls[name][1].set(value)
        dialog.controls["Save bootstrap"][1].set(True)

    standardized_index = analyse_with(standardized, TIES)
    assert_oracle(standardized_index, "standardized")
    assert_cutoff(standardized_index, 0.35)
    row = summary(standardized_index)
    assert row["Raw area A"] == 0.1 and row["Raw area B"] == 0.05 and 0.4 < row["Area B"] < 0.5, row

    def diagonal(dialog):
        dialog.controls["Area"][1].set("Partial")
        dialog.controls["Maximum FPR"][1].set("0.15")
        dialog.controls["Confidence level (%)"][1].set("95")

    app.show("result", standardized_index)
    tools.drive_dialog(tools.AnalysisDialog, diagonal)
    app.edit_analysis()
    wait()
    assert app.runs[standardized_index].options["Maximum FPR"] == 0.15
    assert_oracle(standardized_index, "diagonal_cutoff")
    assert_cutoff(standardized_index, 0.15)

    # 4. Zero variance: the counts stay, no p value is invented and the figure claims nothing more.
    constant_index = analyse_with(lambda d: (tools.pick_method(d, METHOD), columns(d)), CONSTANT)
    row = summary(constant_index)
    assert row["Status"] == engine.STATUS_ZERO and pd.isna(row["Z"]) and pd.isna(row["p"]), row
    assert pd.isna(row["Lower"]) and row["SE"] == 0 and row[COUNTS[0]] == 4, row
    assert_oracle(constant_index, "zero_variance")
    app.show("result", constant_index)
    app.result_tabs.select(0)
    shot(root, "window-independent-roc-zero-variance" + suffix + ".png")

    # 5. Edit a cell and exclude another: every run of the worksheet recalculates, against a direct count of pairs.
    def areas(frame, direction_b=LOWER):
        sign = -1 if direction_b == LOWER else 1
        a = mann_whitney(frame["C_A"].dropna(), frame["P_A"].dropna())
        b = mann_whitney(sign * frame["C_B"].dropna(), sign * frame["P_B"].dropna())
        return a, b

    np.testing.assert_allclose([summary(full_index)["Area A"], summary(full_index)["Area B"]], areas(cohorts),
                               rtol=1e-12)
    app.show("data", COHORTS)
    app.edit_cell(0, 0, "3")
    wait()
    edited = cohorts.copy()
    edited.loc[0, "C_A"] = 3
    np.testing.assert_allclose([summary(full_index)["Area A"], summary(full_index)["Area B"]], areas(edited),
                               rtol=1e-12)
    assert [summary(full_index)[name] for name in COUNTS] == [6, 6, 8, 7], "an edit changes no count"
    styled(full_index)
    app.show("data", COHORTS)
    app.current_grid.select((4, 1))
    app.toggle_exclusion()
    wait()
    kept = edited.copy()
    kept.loc[4, "P_A"] = np.nan
    np.testing.assert_allclose([summary(full_index)["Area A"], summary(full_index)["Area B"]], areas(kept),
                               rtol=1e-12)
    assert [summary(full_index)[name] for name in COUNTS] == [6, 5, 8, 7], "only the excluded stratum shrinks"
    styled(full_index)
    app.show("data", COHORTS)
    app.current_grid.select((4, 1))
    app.toggle_exclusion()
    wait()
    app.show("data", COHORTS)
    app.edit_cell(0, 0, "1")
    wait()
    assert_oracle(full_index, "full")

    # 6. A sample that drops below two values never replaces a previous valid result: the dialog reopens on the
    #    guilty field with the reason, the last numbers stay, and the old numbers come back when the cell returns.
    def few_dialog(dialog):
        tools.pick_method(dialog, METHOD)
        columns(dialog, "C_A", "P_A", "C_B", "P_B")

    def labels(widget):
        found = []
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Label, tk.Label)):
                found.append(str(child.cget("text")))
            found.extend(labels(child))
        return found

    few_index = analyse_with(few_dialog, FEW)
    app.show("data", FEW)
    app.current_grid.select((0, 0))
    app.toggle_exclusion()
    wait()
    before = app.runs[few_index].result
    before_row = summary(few_index).copy()
    assert before_row["Control A N"] == 2 and before_row["Patient A N"] == 3, before_row
    seen = {}

    def recovery(dialog):
        seen["field"] = dialog.fields.select() == str(dialog.field_rows["Control A"][1].master)
        seen["texts"] = " | ".join(labels(dialog))
        shot(dialog, "window-independent-roc-recovery" + suffix + ".png")
        dialog.cancel()
        dialog.ok = lambda *args: None

    reopen = app.reopen_analysis

    def observe_reopening(*args):
        # Start watching when the worker's field error actually opens the dialog.
        tools.drive_dialog(tools.AnalysisDialog, recovery)
        return reopen(*args)

    app.show("data", FEW)
    app.current_grid.select((1, 0))
    with patch.object(app, "reopen_analysis", observe_reopening):
        app.toggle_exclusion()
        wait()
    assert seen.get("field") and "needs at least 2 valid values" in seen["texts"] and "Control A" in seen["texts"], seen
    assert app.runs[few_index].result is before, "the last valid result must stay"
    assert summary(few_index).equals(before_row)
    assert "Change discarded" in app.status.get() or "kept" in app.status.get(), app.status.get()
    app.show("result", few_index)
    root.update()
    shot(root, "window-independent-roc-stale" + suffix + ".png")
    app.show("data", FEW)
    app.current_grid.select((1, 0))
    app.toggle_exclusion()
    wait()
    assert app.runs[few_index].calculation_error is None
    pd.testing.assert_frame_equal(summary_frame(few_index), before.tables[engine.SUMMARY_SHEET])
    app.show("data", FEW)
    app.current_grid.select((0, 0))
    app.toggle_exclusion()
    wait()
    assert summary(few_index)["Control A N"] == 3

    # 7. A refused edit of the dialog changes nothing.
    def bad_edit(dialog):
        dialog.controls["Direction A"][1].set(LOWER)
        dialog.controls["Patient B"][1].set("C_A")
        rejected(dialog, "Patient B", "already used for Control A")
        dialog.cancel()
        dialog.ok = lambda *args: None

    app.show("result", full_index)
    tools.drive_dialog(tools.AnalysisDialog, bad_edit)
    app.edit_analysis()
    wait()
    assert app.runs[full_index].options["Direction A"] == HIGHER and app.runs[full_index].result is not None
    assert not errors, errors

    # Hold the first actual resample until the GUI has exercised Cancel. With a warm
    # process pool, delaying a cohort method in the parent does not delay the children.
    @contextmanager
    def hold_first_draw():
        sampled, resume = Event(), Event()
        draw = engine._draws

        def held_draw(rng, sizes):
            values = draw(rng, sizes)
            if not sampled.is_set():
                sampled.set()
                if not resume.wait(30):
                    raise AssertionError("The GUI did not release the first bootstrap draw")
            return values

        with patch.object(engine, "_draws", held_draw):
            try:
                yield sampled, resume
            finally:
                resume.set()

    def wait_for_worker(sampled):
        deadline = time.monotonic() + 20
        while not (sampled.is_set() and app.calculation and app.cancel_button.winfo_viewable()):
            assert time.monotonic() < deadline, (
                "Cancel calculation did not become visible during bootstrap",
                sampled.is_set(), app.cancel_button.winfo_manager(), root.state(), root.geometry())
            root.update()
            time.sleep(.02)
        root.update()

    def large(dialog):
        tools.pick_method(dialog, METHOD)
        columns(dialog, "C1", "P1", "C2", "P2")
        dialog.controls["Area"][1].set("Standardized partial")
        dialog.controls["Maximum FPR"][1].set("0.2")
        dialog.controls["Bootstrap replicates"][1].set("2500")

    count = len(app.runs)
    with hold_first_draw() as (sampled, resume):
        app.show("data", LARGE)
        tools.drive_dialog(tools.AnalysisDialog, large)
        app.choose_analysis()
        wait_for_worker(sampled)
        root.update()
        button = app.cancel_button
        placement = {"viewable": bool(button.winfo_viewable()), "top": button.winfo_rooty(),
                     "bottom": button.winfo_rooty() + button.winfo_height(), "window_height": root.winfo_height(),
                     "screen_height": screen[1]}
        (out / "cancel-button.json").write_text(json.dumps(placement) + "\n", encoding="utf-8")
        assert placement["viewable"] and 0 <= placement["top"] < placement["bottom"] <= screen[1], placement
        assert button.winfo_rootx() + button.winfo_width() <= screen[0]
        shot(root, "window-independent-roc-progress" + suffix + ".png")
        button.invoke()
        resume.set()
        wait()
        assert not app.cancel_button.winfo_manager()
        assert len(app.runs) == count and len(app.tables[LARGE].analyses) == 0, "a cancelled new analysis adds nothing"
        assert "cancelled" in app.status.get().lower() and "No analysis was added" in app.status.get(), app.status.get()
        shot(root, "window-independent-roc-cancelled" + suffix + ".png")

    # Recalculating an existing run: the last completed result stays.
    def large_run(dialog):
        large(dialog)
        dialog.controls["Bootstrap replicates"][1].set("200")

    large_index = analyse_with(large_run, LARGE)
    first = app.runs[large_index].result

    def longer(dialog):
        dialog.controls["Bootstrap replicates"][1].set("2500")

    with hold_first_draw() as (sampled, resume):
        app.show("result", large_index)
        tools.drive_dialog(tools.AnalysisDialog, longer)
        app.edit_analysis()
        wait_for_worker(sampled)
        app.cancel_calculation()
        resume.set()
        wait()
        assert app.runs[large_index].result is first and app.runs[large_index].options[
            "Bootstrap replicates"] == 200, "the recipe and its tables stay when the update is cancelled"
        assert "cancelled" in app.status.get().lower() and "kept" in app.status.get(), app.status.get()
    # The next calculation is unaffected by the cancelled one.
    app.recalculate(large_index)
    wait()
    pd.testing.assert_frame_equal(table(large_index, engine.SUMMARY_SHEET), first.tables[engine.SUMMARY_SHEET])

    # 9. Italian: translated captions, choices and errors; canonical values in the recipe.
    original_language = i18n.active_language()
    italian_recipe = {"Control A": "C_A", "Patient A": "P_A", "Control B": "C_B", "Patient B": "P_B",
                      "Direction A": HIGHER, "Direction B": LOWER, "Area": "Full", "Inference": "DeLong",
                      "Confidence level (%)": 95.0}

    def italian(dialog):
        tools.pick_method(dialog, METHOD)
        captions = {name: dialog.field_rows[name][0].cget("text") for name in (
            "Control A", "Patient A", "Control B", "Patient B", "Direction A", "Direction B", "Area", "Inference",
            "Confidence level (%)")}
        assert captions["Control A"] == "Controllo A" and captions["Patient B"] == "Paziente B", captions
        assert captions["Area"] == "Area" and captions["Inference"] == "Inferenza", captions
        assert [dialog.fields.tab(i, "text") for i in range(2)][1] == "Area e inferenza"
        direction = dialog.field_rows["Direction A"][1]
        assert list(direction.cget("values")) == ["Maggiore nei pazienti", "Minore nei pazienti"], direction.cget(
            "values")
        assert direction.get() == "Maggiore nei pazienti" and dialog.controls["Direction A"][1].get() == HIGHER
        dialog.controls["Control A"][1].set("")
        rejected(dialog, "Control A", "Scegli una colonna", caption=captions["Control A"])
        columns(dialog, "C_A", "C_A", "C_B", "P_B")
        rejected(dialog, "Patient A", "è già usata per", caption=captions["Patient A"])
        columns(dialog)
        dialog.field_rows["Direction B"][1].set("Minore nei pazienti")
        assert dialog.controls["Direction B"][1].get() == LOWER
        area = dialog.field_rows["Area"][1]
        assert list(area.cget("values")) == ["Completa", "Parziale", "Parziale standardizzata"], area.cget("values")
        area.set("Parziale")
        dialog.update()
        assert dialog.controls["Area"][1].get() == "Partial" and dialog.controls["Inference"][
            1].get() == "Percentile bootstrap"
        dialog.controls["Maximum FPR"][1].set("2")
        rejected(dialog, "Maximum FPR", "maggiore di 0 e minore di 1", "window-independent-roc-it-error.png",
                 caption=i18n.ui("Maximum FPR"))
        area.set("Completa")
        dialog.update()
        assert dialog.controls["Area"][1].get() == "Full" and not placed(dialog, "Maximum FPR")
        dialog.field_rows["Inference"][1].set("DeLong")
        assert dialog.controls["Inference"][1].get() == "DeLong"
        dialog.fields.select(0)
        dialog.update()
        shot(dialog, "window-independent-roc-it" + suffix + ".png")

    try:
        i18n.set_language("it")
        italian_index = analyse_with(italian, COHORTS)
        assert app.runs[italian_index].options == italian_recipe, app.runs[italian_index].options
        assert_oracle(italian_index, "full")
        app.show("graph", italian_index)
        root.update()
        shot(root, "window-independent-roc-it-graph" + suffix + ".png")
        i18n.set_language("en")

        def english_again(dialog):
            shown = [dialog.field_rows[name][1].get() for name in ("Direction A", "Direction B", "Area")]
            assert shown == [HIGHER, LOWER, "Full"], shown
            assert dialog.field_rows["Confidence level (%)"][0].cget("text") == "Confidence level (%)"

        app.show("result", italian_index)
        tools.drive_dialog(tools.AnalysisDialog, english_again)
        app.edit_analysis()
        wait()
        assert app.runs[italian_index].options == italian_recipe

        # Partial area with a decimal comma: the recipe keeps the number, and the oracle of the same cutoff matches.
        def italian_partial(dialog):
            tools.pick_method(dialog, METHOD)
            dialog.field_rows["Area"][1].set("Parziale")
            dialog.update()
            controls = dialog.controls
            assert controls["Inference"][1].get() == "Percentile bootstrap"
            controls["Maximum FPR"][1].set("0")
            rejected(dialog, "Maximum FPR", "maggiore di 0 e minore di 1", caption=i18n.ui("Maximum FPR"))
            controls["Maximum FPR"][1].set("0,15")
            controls["Bootstrap replicates"][1].set("200")
            controls["Bootstrap seed"][1].set(str(SEED))
            controls["Save bootstrap"][1].set(True)
            dialog.fields.select(1)
            dialog.update()
            shot(dialog, "window-independent-roc-it-partial" + suffix + ".png")

        i18n.set_language("it")
        comma_index = analyse_with(italian_partial, TIES)
        assert app.runs[comma_index].options == {
            "Control A": "C_A", "Patient A": "P_A", "Control B": "C_B", "Patient B": "P_B", "Direction A": HIGHER,
            "Direction B": HIGHER, "Area": "Partial", "Maximum FPR": 0.15, "Inference": "Percentile bootstrap",
            "Confidence level (%)": 95.0, "Bootstrap replicates": 200, "Bootstrap seed": SEED,
            "Save bootstrap": True}, app.runs[comma_index].options
        assert_oracle(comma_index, "diagonal_cutoff")
        assert_cutoff(comma_index, 0.15)
        app.show("result", comma_index)
        app.result_tabs.select(0)
        shot(root, "window-independent-roc-it-result" + suffix + ".png")
        app.show("graph", comma_index)
        root.update()
        shot(root, "window-independent-roc-it-partial-graph" + suffix + ".png")
    finally:
        i18n.set_language(original_language)

    # 10. Inspector and Format Graph on the figure.
    app.show("graph", partial_index)
    root.update()
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
    assert "#9b4174" in str(app.runs[partial_index].style), app.runs[partial_index].style
    app.toggle_inspector()
    root.update()
    tools.drive_dialog(GraphFormatDialog, lambda dialog: dialog.inputs["title"].set("Markers A and B at low FPR"))
    app.format_graph()
    wait()
    assert app.runs[partial_index].result.figure.axes[0].get_title() == "Markers A and B at low FPR"
    app.show("graph", partial_index)
    root.update()

    # 11. Exports: CSV of each sheet, then PNG, SVG and PDF of the figure.
    app.show("result", partial_index)
    for position, name in enumerate((engine.SUMMARY_SHEET, engine.CURVE_A_SHEET, engine.CURVE_B_SHEET,
                                     engine.BOOTSTRAP_SHEET)):
        app.result_tabs.select(position)
        target = out / f"independent-roc-{position}.csv"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        exported = pd.read_csv(target, index_col=0, encoding="utf-8-sig")
        assert len(exported) >= 1, name
        if name == engine.SUMMARY_SHEET:
            assert exported.loc[0, "Status"] == engine.STATUS_BOOTSTRAP and exported.loc[0, "Control A N"] == 5
            assert exported.loc[0, "Area type"] == "Partial" and list(exported.columns) == engine.SUMMARY_COLUMNS
        if name == engine.BOOTSTRAP_SHEET:
            assert len(exported) == 200
    app.show("graph", partial_index)
    for extension, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
        target = out / f"independent-roc.{extension}"
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)):
            app.export()
        content = target.read_bytes()
        assert (magic in content[:400] or (extension == "svg" and magic in content)) and len(content) > 1000, extension

    # 11b. The figure in a layout; the paired comparison of the same worksheet keeps working beside the new one.
    layout = compose_layout("ROC layout", 1, [app.runs[partial_index].result.figure])
    layout.savefig(directory / "independent-roc-layout.png", dpi=80)
    app.layouts.append(Layout("ROC layout", 1, [app.runs[partial_index].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()
    shot(root, "window-independent-roc-layout" + suffix + ".png")
    (directory / "independent-roc-layout.png").replace(out / "independent-roc-layout.png")

    def paired_dialog(dialog):
        tools.pick_method(dialog, "Compare paired ROC curves")
        for name, column in (("Control A", "C_A"), ("Patient A", "P_A"), ("Control B", "C_B"), ("Patient B", "P_B")):
            dialog.controls[name][1].set(column)

    app.show("data", TIES)
    tools.drive_dialog(tools.AnalysisDialog, paired_dialog)
    app.choose_analysis()
    wait()
    paired_index = len(app.runs) - 1
    assert app.runs[paired_index].method == "Compare paired ROC curves", app.runs[paired_index].method
    paired_options = dict(app.runs[paired_index].options)
    paired_tables = {k: v.copy() for k, v in app.runs[paired_index].result.tables.items()}
    assert list(paired_tables) == ["Paired ROC comparison", "Curve points A", "Curve points B"], list(paired_tables)

    # 12. Save, reopen and open the graph before the worksheet: canonical recipes, same tables, same figure.
    def figure_state(run):
        axes = run.result.figure.axes[0]
        marks = {child.get_gid(): np.asarray(child.get_xdata(), float).tolist() for child in axes.lines
                 if child.get_gid()}
        return axes.get_title(), axes.get_xlabel(), tuple(round(v, 10) for v in axes.get_xlim()), marks

    expected = {(run.title, run.slot): (dict(run.options), {k: v.copy() for k, v in run.result.tables.items()},
                                        figure_state(run))
                for run in app.runs if run.method == METHOD and run.result is not None}
    assert len(expected) == 8, sorted(expected)
    app.path = directory / "independent-roc-saved.alab"
    assert app.save()
    app.import_file(app.path)
    for position, run in enumerate(app.runs):
        if run.method in (METHOD, "Compare paired ROC curves"):
            app.open_sheet(("graph", position))
            wait()
    reopened = {(run.title, run.slot): run for run in app.runs}
    for key, (saved_options, tables, figure) in expected.items():
        assert reopened[key].options == saved_options, (key, reopened[key].options)
        for name, frame in tables.items():
            pd.testing.assert_frame_equal(reopened[key].result.tables[name], frame, rtol=1e-9)
        if reopened[key].title != COHORTS or reopened[key].options["Area"] == "Full":
            assert figure_state(reopened[key])[:3] == figure[:3], key
    paired_again = next(run for run in app.runs if run.method == "Compare paired ROC curves")
    assert paired_again.options == paired_options and set(paired_again.result.tables) == set(paired_tables)
    for name, frame in paired_tables.items():
        pd.testing.assert_frame_equal(paired_again.result.tables[name], frame, rtol=1e-9)
    key = next(k for k, v in expected.items() if v[0]["Area"] == "Partial" and k[0] == TIES
               and v[0]["Maximum FPR"] == 0.35)
    reopened_index = next(i for i, run in enumerate(app.runs) if (run.title, run.slot) == key)
    assert "#9b4174" in str(reopened[key].style) and engine.BOOTSTRAP_SHEET in reopened[key].result.tables
    app.show("graph", reopened_index)
    root.update()
    shot(root, "window-independent-roc-reopened" + suffix + ".png")

    # 13. Use Result as Data from the new sheets keeps the numbers.
    before_tables = set(app.tables)
    for position in (0, 1):
        app.show("result", reopened_index)
        app.result_tabs.select(position)
        app.use_result_as_data()
    created = {name: app.tables[name].raw for name in set(app.tables) - before_tables}
    assert len(created) == 2, created
    assert any(list(f.columns) == engine.SUMMARY_COLUMNS and len(f) == 1 for f in created.values())
    assert any(list(f.columns) == engine.CURVE_COLUMNS for f in created.values())
    wait()
    assert app.pending is None and not errors, errors
